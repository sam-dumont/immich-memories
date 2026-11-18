"""A confirmed special day's title, written from a short list of what the library records about it.

The day question names the day as it decides it, from one line per picture, and on a French
install its titles came back generic ("The Gathering") or in English. Once the day is decided,
its title is asked again from a few facts: how big the day was and where, who was on the most
pictures, the occasion the library knows of (a birth, a birthday, a public holiday), what the
activity heads saw people doing, and four of its captions. The answer goes through the same
guard as every special-day title (`title.title_the_day_can_keep`).

Measured offline on 115 stored days of a French catalogue against the day question's titles:
generic titles 22 to 1, English titles 108 to 0, no wrong names, and half a second a day
against nearly nine.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from immich_memories.analysis.facts.line_fields import DOING
from immich_memories.analysis.judgments.strict_json import final_json_object
from immich_memories.analysis.llm.failures import stop_if_this_is_our_bug
from immich_memories.analysis.places.home_radius import near_home_of
from immich_memories.analysis.special_days import detection
from immich_memories.analysis.special_days.title import (
    honest_title,
    title_language,
    title_the_day_can_keep,
)

if TYPE_CHECKING:
    from datetime import date

    from immich_memories.analysis.special_days.detection import SpecialDay
    from immich_memories.db import Store

logger = logging.getLogger(__name__)

# On the prompt's first line, so a banked title from an older prompt is asked again.
TITLE_VERSION = "special-day-title-v1"

_PROMPT = """Name this day of a family's photo library, for the title of its film. {version}
{facts}

Write its title in {language}, at most 6 words: what the day was (name it: a birthday, a
wedding, a race, a festival, a trip...), and whose day it was by first name when it was one
person's. Not the date, and not a place on its own. Use only these facts.
JSON only: {{"title":"..."}}"""

# A title of six words in JSON; thinking, where a host does it, is budgeted beside this.
_ANSWER_TOKENS = 60
_TIMEOUT_SECONDS = 300
# The people, towns, activities and captions the facts name, most pictures first.
_PEOPLE = 4
_TOWNS = 2
_DOING_SHOWN = 3
_CAPTIONS = 4
_CAPTION_CHARS = 140


@dataclass(frozen=True)
class DayFacts:
    """What the title of one day is written from."""

    pictures: int
    hours: int
    near_home: bool | None
    towns: Counter[str]
    who: Counter[str]
    role_of: Mapping[str, str]
    born: Sequence[str]
    birthday: Sequence[str]
    holiday: str
    acts: Counter[str]
    said: Sequence[str]


def facts_text(facts: DayFacts) -> str:
    """The facts as the prompt lists them: the day's size and place, who, the occasion the
    library knows of, what the pictures show, and a few of its captions in order."""
    near = {True: "at home", False: "away from home", None: "place not recorded"}[facts.near_home]
    lines = [f"THE DAY: {facts.pictures} pictures over {facts.hours} hours, {near}."]
    if facts.towns:
        lines.append("WHERE: " + "; ".join(town for town, _n in facts.towns.most_common(_TOWNS)))
    who = "; ".join(
        f"{_first(name)} ({facts.role_of[name]})" if name in facts.role_of else _first(name)
        for name, _n in facts.who.most_common(_PEOPLE)
    )
    if len(facts.who) > _PEOPLE:
        who += f"; and {len(facts.who) - _PEOPLE} others"
    lines.append(f"WHO, on the most pictures: {who or 'no one named'}")
    occasion = []
    if facts.born:
        occasion.append("the birth of " + ", ".join(_first(name) for name in facts.born))
    if facts.birthday:
        occasion.append("the birthday of " + ", ".join(_first(name) for name in facts.birthday))
    if facts.holiday:
        occasion.append(facts.holiday)
    if occasion:
        lines.append("THE OCCASION: " + "; ".join(occasion))
    doing: Counter[str] = Counter()
    for label, count in facts.acts.items():
        if word := DOING.get(label):
            doing[word] += count
    if doing:
        shown = doing.most_common(_DOING_SHOWN)
        lines.append("WHAT THE PICTURES SHOW: " + ", ".join(f"{w} ({c})" for w, c in shown))
    if facts.said:
        lines.append("SOME OF THEM, in order:")
        lines += [f"- {said[:_CAPTION_CHARS]}" for said in facts.said]
    return "\n".join(lines)


def title_prompt(facts: DayFacts, locale: str) -> str:
    """The question that asks a day's title in `locale`'s language from its facts."""
    return _PROMPT.format(
        version=TITLE_VERSION, facts=facts_text(facts), language=title_language(locale)
    )


@dataclass(frozen=True)
class FactsTitle:
    """Writes a confirmed day's title from its facts: what the library records beyond the
    day's own pictures, and the reader that is asked."""

    llm_config: Any
    judgments: Store | None
    locale: str = "en"
    home: tuple[float, float] | None = None
    # Immich person id -> close family role, and close family birth dates -> who.
    roles: Mapping[str, str] = field(default_factory=dict)
    births: Mapping[date, Sequence[str]] = field(default_factory=dict)
    holidays: Mapping[date, str] = field(default_factory=dict)
    captions: Mapping[str, str] | None = None
    # Asset id -> the activity head's label.
    activities: Mapping[str, str] = field(default_factory=dict)

    def __call__(self, day: date, items: list, verdict: SpecialDay) -> SpecialDay:
        """The verdict with the title written from the day's facts, or as it was when the
        reader gives nothing usable."""
        window = detection.window_that_holds_the_day(
            verdict.window or detection.event_window(items), items
        )
        kept = (
            [a for a in items if window[0] <= a.file_created_at <= window[1]] if window else items
        )
        facts = self.facts_of(day, kept)
        evidence = facts_text(facts)
        written = self._written(title_prompt(facts, self.locale))
        if not written:
            return verdict
        title = title_the_day_can_keep(
            written, kept, evidence=evidence, locale=self.locale
        ) or honest_title(kept, what=written, evidence=evidence, locale=self.locale)
        return replace(verdict, title=title) if title else verdict

    def facts_of(self, day: date, kept: list) -> DayFacts:
        """The facts of a day from the pictures a film of it is cut from."""
        who, role_of = self._who(kept)
        exifs = [exif for a in kept if (exif := getattr(a, "exif_info", None))]
        located = [
            (e.latitude, e.longitude) for e in exifs if getattr(e, "latitude", None) is not None
        ]
        captions = self.captions or {}
        described = [a for a in kept if captions.get(a.id)]
        return DayFacts(
            pictures=len(kept),
            hours=len({detection.capture_clock(a).hour for a in kept}),
            near_home=near_home_of(self.home, located),
            towns=Counter(city for e in exifs if (city := getattr(e, "city", None))),
            who=who,
            role_of=role_of,
            born=tuple(self.births.get(day, ())),
            birthday=self._birthdays(day),
            holiday=self.holidays.get(day, ""),
            acts=Counter(label for a in kept if (label := self.activities.get(a.id))),
            said=tuple(
                captions[a.id] for a in detection.sample_across_day(described, count=_CAPTIONS)
            ),
        )

    def _who(self, kept: list) -> tuple[Counter[str], dict[str, str]]:
        """Who is on how many of the pictures, and the close family role of those who have one."""
        who: Counter[str] = Counter()
        role_of: dict[str, str] = {}
        for asset in kept:
            for person in getattr(asset, "people", None) or []:
                if not (name := getattr(person, "name", "")):
                    continue
                who[name] += 1
                if (role := self.roles.get(getattr(person, "id", ""))) is not None:
                    role_of[name] = role
        return who, role_of

    def _birthdays(self, day: date) -> list[str]:
        """Close family born on this day of an earlier year."""
        return sorted(
            {
                name
                for born, names in self.births.items()
                if (born.month, born.day) == (day.month, day.day) and born.year < day.year
                for name in names
            }
        )

    def _written(self, prompt: str) -> str:
        """The title the reader wrote, or nothing when it could not be asked or read."""
        try:
            raw = _ask(prompt, self.llm_config, self.judgments)
        except Exception as exc:  # noqa: BLE001 - an unreachable model keeps the day's title
            stop_if_this_is_our_bug(exc, "special-day title")
            logger.warning("The special-day title could not be asked (%s)", type(exc).__name__)
            return ""
        return _title_in(raw)


def _ask(prompt: str, llm_config: Any, judgments: Store | None) -> str:
    """One title question, banked when a store is given so a repeated scan pays for it once."""
    if judgments is None:
        from immich_memories.analysis.llm.query import query_llm

        return asyncio.run(
            query_llm(
                prompt,
                llm_config,
                temperature=0.1,
                timeout_seconds=_TIMEOUT_SECONDS,
                response_format={"type": "json_object"},
            )
        )
    from immich_memories.analysis.judgments.text_gateway import QueryTextRequester
    from immich_memories.analysis.judgments.text_request import TextRequest

    request = TextRequest(
        prompt=prompt,
        llm_config=llm_config,
        judgments=judgments,
        max_tokens=_ANSWER_TOKENS,
        timeout_seconds=_TIMEOUT_SECONDS,
        json_object=True,
        response_format={"type": "json_object"},
        json_fields=("title",),
    )
    return asyncio.run(QueryTextRequester().request(request, accepts=_readable)).raw


def _answer(raw: str | None) -> dict[str, Any] | None:
    return final_json_object(raw) if raw else None


def _readable(raw: str) -> bool:
    return isinstance((_answer(raw) or {}).get("title"), str)


def _title_in(raw: str | None) -> str:
    title = (_answer(raw) or {}).get("title")
    return title.strip() if isinstance(title, str) else ""


def _first(name: str) -> str:
    return name.split()[0] if name.split() else name
