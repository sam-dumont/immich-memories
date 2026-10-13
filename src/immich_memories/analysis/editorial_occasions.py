"""A day the household keeps is its own story, named from its facts (no model, #2486).

The rules reader groups a week at home into one story. A child's birthday or the grandparents'
afternoon then sat inside "the week", weighed like the errands around it, and the film could
spend its one picture of that week on the tram. Two facts the household itself recorded make
such a day an occasion:

- a birthday: a household member, or close family, on any of the day's pictures on the day
  their Immich birth date comes round: the date is the evidence, so one picture of them on it
  is enough (a film of two people may hold only one frame of both that day);
- a visit: close family who are not of the owner's household (the owner's parents, say) on at
  least `OCCASION_MIN_PICTURES` of the day's pictures, and on at most `VISIT_MAX_DAYS`
  photographed days of the period, so a parent who lives in is never "visiting".

A birthday film names its subject's birthday the same way: the request's own birthday
(`--birthday 08-30`) is that evidence, whoever the subject is to the owner, so every
photographed occurrence of it in the film is their birthday's story.

The name and the purpose are written from those facts only ("Kit's birthday", "Kit turns five";
"Pat and Lou's visit"), never an event the facts do not carry, in the film's language
(`story.*` in its film-text catalogue). Only stories at home are read: a trip names itself.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import chain

from babel.lists import format_list

from immich_memories.analysis.editorial_story_names import story_text, story_text_n
from immich_memories.i18n import babel_locale

OCCASION_MIN_PICTURES = 2
VISIT_MAX_DAYS = 3
# The owner's household, as relations on an annotation line state them; everyone else that
# `is_close_family` admits (a parent of the owner) visits.
HOUSEHOLD_RELATIONS = frozenset({"library owner", "partner", "spouse", "child", "son", "daughter"})
_NUMBERS = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
    "twenty",
]


@dataclass(frozen=True)
class Occasion:
    """One day the household keeps, and what its story is called."""

    kind: str
    day: str
    people: tuple[str, ...]
    name: str
    purpose: str


def find_occasions(
    day_people: Mapping[str, Counter[str]],
    *,
    relation_of: Mapping[str, str],
    birth_dates: Mapping[str, str | None],
    close_family: frozenset[str],
    locale: str,
    celebrated: Mapping[str, str] | None = None,
) -> dict[str, Occasion]:
    """Each photographed day's occasion, if it has one.

    `day_people` counts, for each ISO day, the pictures each person is on. `relation_of` is each
    person's relation to the owner as the lines state it; `close_family` the names the owner's
    registry calls close family. `celebrated` is the birthday a birthday film was asked for, by
    the name of its subject ("MM-DD"): their birthday on any day it comes round, family or not.
    """
    days_seen = Counter(chain.from_iterable(day_people.values()))
    household = {name for name, rel in relation_of.items() if _household(rel)}
    found: dict[str, Occasion] = {}
    for day, counts in sorted(day_people.items()):
        # Most pictures first, then by name: ties never depend on the order lines were read.
        seen = [name for name, _ in sorted(counts.items(), key=lambda row: (-row[1], row[0]))]
        present = [name for name in seen if counts[name] >= OCCASION_MIN_PICTURES]
        if birthday := _birthday(
            day, seen, birth_dates, household | close_family, celebrated or {}, locale
        ):
            found[day] = birthday
            continue
        visitors = [
            name
            for name in present
            if name in close_family and name not in household and days_seen[name] <= VISIT_MAX_DAYS
        ]
        if visitors:
            names = spoken_list(visitors, locale)
            found[day] = Occasion(
                "visit",
                day,
                tuple(visitors),
                story_text("story.visit", locale, names=names),
                story_text_n("story.comes_over", len(visitors), locale, names=names),
            )
    return found


def _household(relation: str) -> bool:
    words = relation.casefold()
    return any(word == words or words.startswith(f"{word} ") for word in HOUSEHOLD_RELATIONS)


def _birthday(
    day: str,
    present: Sequence[str],
    birth_dates: Mapping[str, str | None],
    family: set[str] | frozenset[str],
    celebrated: Mapping[str, str],
    locale: str,
) -> Occasion | None:
    for name in present:
        born = birth_dates.get(name)
        if name in family and born and born[5:10] == day[5:10] and born[:4] < day[:4]:
            age = int(day[:4]) - int(born[:4])
            return Occasion(
                "birthday",
                day,
                (name,),
                story_text("story.birthday", locale, name=name),
                story_text_n("story.turns", age, locale, name=name, age=_number(age, locale)),
            )
        if celebrated.get(name) == day[5:10]:
            # The request names the day, not the year they were born: the name says it all.
            named = story_text("story.birthday", locale, name=name)
            return Occasion("birthday", day, (name,), named, named)
    return None


def _number(n: int, locale: str) -> str:
    """An age as the purpose writes it: spelled out in English ("five"), a numeral elsewhere."""
    return _NUMBERS[n] if locale == "en" and 0 <= n < len(_NUMBERS) else str(n)


def spoken_list(names: Sequence[str], locale: str) -> str:
    """Names as a sentence says them: "Pat", "Pat and Lou", "Pat, Lou and Remy" ("et", "und")."""
    if len(names) <= 1:
        return "".join(names)
    # British English, like the English film text: no comma before the last "and".
    return format_list(list(names), locale=babel_locale("en_GB" if locale == "en" else locale))
