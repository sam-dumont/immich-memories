"""What a film's period was about, in two short sentences: the thesis its vote and summary read.

The period's banked account is a navigation note over the whole period, in English: what
happened where, and the broad pattern. It was never a film's thesis, yet the thesis-fit vote
read it raw. The thesis is asked of the cut instead, in the film's language, from what a small
reader can use: the cut's four heaviest stories with their share of its shots and what the
readings of their episodes say, and the people on the most pictures (#2594).

Measured on 80 stored cuts with the small reader, against the raw account it replaces: it named
who and where in 80 (45), read generic in 13 (55), named no one wrongly, and ran 167 characters
on average (766).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import cached_property
from operator import itemgetter
from typing import Any, Protocol

from immich_memories.analysis.judgments.strict_json import final_json_object
from immich_memories.analysis.reading.episode_block import people_on
from immich_memories.analysis.stories.replies import WEIGHTS

THESIS_VERSION = "period-thesis-v1"
THESIS_MAX_TOKENS = 200
# The heaviest stories the thesis reads, and the episode readings it reads of each.
_OCCASIONS = 4
_READINGS_EACH = 2
# Two short sentences; a longer answer is cut, not refused.
_MAX_CHARS = 600

_PROMPT = """Say what this period of a family's life was about, for the film made of it. {version}
THE FILM: {scope}.
{occasion}PEOPLE, those on the most pictures: {people}
THE BIGGEST OCCASIONS, largest first, each with what its pictures show:
{occasions}

Write at most 2 short sentences in {language}. The first: what the biggest occasion was (name it:
a birthday, Christmas, a trip, a walk...), who was there by first name, and where. The second, only if the period held more: the next one or two. Say what they did, never "spent time together". Use only these facts. No ids.
JSON only: {{"thesis":"..."}}"""


class EpisodeReading(Protocol):
    """What one episode's reading says happened, and the pictures it is about."""

    @property
    def full_asset_ids(self) -> tuple[str, ...]: ...

    @property
    def what_happened(self) -> str: ...


@dataclass(frozen=True)
class Occasion:
    """One of the cut's heaviest stories, as the thesis reads it."""

    title: str
    weight: str
    clips: int
    readings: tuple[str, ...]


@dataclass(frozen=True)
class FilmShots:
    """A cut as its thesis and its summary read it: its shots, the stories they belong to, and
    what the readings of the episodes they sit in say."""

    carriers: Sequence[Mapping[str, Any]]
    stories: Sequence[Mapping[str, Any]]
    readings: Sequence[EpisodeReading] = ()
    line_of: Callable[[str], str | None] = lambda _asset: ""

    def occasions(self, count: int = _OCCASIONS, readings: int = _READINGS_EACH) -> list[Occasion]:
        """The stories the cut shows, heaviest first, then most shots, then earliest; each with
        the readings of the episodes holding most of its shots."""
        story_of = {str(story.get("key")): story for story in self.stories}
        ranked = []
        for key, clips in self._by_story.items():
            story = story_of.get(key) or {}
            weight = str(story.get("weight") or "none")
            rank = (_weight_rank(weight), -len(clips), _first_day(story))
            ranked.append((rank, key, weight, clips))
        ranked.sort(key=itemgetter(0))
        return [
            Occasion(
                title=_story_name(story_of.get(key) or {}),
                weight=weight,
                clips=len(clips),
                readings=tuple(
                    text for e in self._episodes_of(clips)[:readings] if (text := self._said(e))
                ),
            )
            for _rank, key, weight, clips in ranked[:count]
        ]

    def groups(self, count: int) -> list[tuple[int, str]]:
        """The cut's shots by story, most shots first: how many, and what the episode holding
        most of them was read as ("" when it was not read)."""
        rows = []
        for clips in self._by_story.values():
            episodes = self._episodes_of(clips)
            rows.append((len(clips), self._said(episodes[0]) if episodes else ""))
        return sorted(rows, key=lambda row: -row[0])[:count]

    def people(self) -> str:
        """Who is on the most of the cut's pictures, said as an episode's People line says it."""
        shown = sorted({e for e in self._clip_episodes if e is not None})
        lines = [
            self.line_of(asset) or "" for e in shown for asset in self.readings[e].full_asset_ids
        ]
        lines += [str(carrier.get("line") or "") for carrier in self.carriers]
        return people_on(lines)

    @cached_property
    def _by_story(self) -> dict[str, list[int]]:
        found: dict[str, list[int]] = {}
        for index, carrier in enumerate(self.carriers):
            found.setdefault(str(carrier.get("story_episode") or ""), []).append(index)
        return found

    @cached_property
    def _clip_episodes(self) -> list[int | None]:
        """The reading each shot's episode has, by its index; None for a shot nothing read."""
        where = {
            asset: index
            for index, reading in enumerate(self.readings)
            for asset in reading.full_asset_ids
        }
        return [
            next(
                (where[a] for a in (c.get("asset_id"), *(c.get("members") or ())) if a in where),
                None,
            )
            for c in self.carriers
        ]

    def _episodes_of(self, clips: Sequence[int]) -> list[int]:
        held = Counter(e for i in clips if (e := self._clip_episodes[i]) is not None)
        return [episode for episode, _count in held.most_common()]

    def _said(self, episode: int) -> str:
        return self.readings[episode].what_happened.strip()


def thesis_prompt(shots: FilmShots, *, scope: str, occasion: str, language: str) -> str:
    """The question that asks a cut's thesis, in `language`, from its own stories and people."""
    return _PROMPT.format(
        version=THESIS_VERSION,
        scope=scope,
        occasion=f"THE OCCASION: {occasion}.\n" if occasion else "",
        people=shots.people() or "no one named",
        occasions=_occasion_lines(shots) or "(none read)",
        language=language,
    )


def read_thesis(judge, prompt: str) -> str:
    """The reader's thesis for this prompt. ValueError when the answer holds none."""
    raw = judge.ask(
        "period-thesis",
        prompt,
        max_tokens=THESIS_MAX_TOKENS,
        json_object=True,
        json_fields=("thesis",),
    )
    thesis = (final_json_object(raw) or {}).get("thesis")
    text = " ".join(thesis.split())[:_MAX_CHARS].strip() if isinstance(thesis, str) else ""
    if not text:
        raise ValueError("the model gave no usable period thesis")
    return text


def _occasion_lines(shots: FilmShots) -> str:
    total = len(shots.carriers)
    lines = []
    for number, occasion in enumerate(shots.occasions(), start=1):
        share = f"({occasion.weight}; {occasion.clips} of {total} shots)"
        head = f"{number}. {occasion.title} {share}" if occasion.title else f"{number}. {share}"
        lines.append("\n".join([head, *(f"   - {said}" for said in occasion.readings)]))
    return "\n".join(lines)


def _story_name(story: Mapping[str, Any]) -> str:
    """A story's name, or none when the rules named it with its place list ("posing at X /
    working at Y"): its readings say what happened instead."""
    trip = story.get("trip")
    name = str((trip if isinstance(trip, str) and trip.strip() else story.get("title")) or "")
    return "" if " / " in name else name.strip()


def _weight_rank(weight: str) -> int:
    return WEIGHTS.index(weight) if weight in WEIGHTS else len(WEIGHTS)


def _first_day(story: Mapping[str, Any]) -> str:
    days = story.get("days") or ()
    return str(days[0]) if days else ""
