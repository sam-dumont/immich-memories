"""A day the household keeps is its own story, named from its facts (no model, #2486).

The rules reader groups a week at home into one story. A child's birthday or the grandparents'
afternoon then sat inside "the week", weighed like the errands around it, and the film could
spend its one picture of that week on the tram. Two facts the household itself recorded make
such a day an occasion:

- a birthday: a household member, or close family, on at least `OCCASION_MIN_PICTURES` of the
  day's pictures on the day their Immich birth date comes round;
- a visit: close family who are not of the owner's household (the owner's parents, say) on at
  least `OCCASION_MIN_PICTURES` of the day's pictures, and on at most `VISIT_MAX_DAYS`
  photographed days of the period, so a parent who lives in is never "visiting".

The name and the purpose are written from those facts only ("Kit's birthday", "Kit turns five";
"Pat and Lou's visit"), never an event the facts do not carry. Only stories at home are read:
a trip names itself.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import chain

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
) -> dict[str, Occasion]:
    """Each photographed day's occasion, if it has one.

    `day_people` counts, for each ISO day, the pictures each person is on. `relation_of` is each
    person's relation to the owner as the lines state it; `close_family` the names the owner's
    registry calls close family.
    """
    days_seen = Counter(chain.from_iterable(day_people.values()))
    household = {name for name, rel in relation_of.items() if _household(rel)}
    found: dict[str, Occasion] = {}
    for day, counts in sorted(day_people.items()):
        present = [name for name, n in counts.most_common() if n >= OCCASION_MIN_PICTURES]
        if birthday := _birthday(day, present, birth_dates, household | close_family):
            found[day] = birthday
            continue
        visitors = [
            name
            for name in present
            if name in close_family and name not in household and days_seen[name] <= VISIT_MAX_DAYS
        ]
        if visitors:
            names = spoken_list(visitors)
            verb = "come" if len(visitors) > 1 else "comes"
            found[day] = Occasion(
                "visit", day, tuple(visitors), f"{names}'s visit", f"{names} {verb} over"
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
) -> Occasion | None:
    for name in present:
        born = birth_dates.get(name)
        if name in family and born and born[5:10] == day[5:10] and born[:4] < day[:4]:
            age = int(day[:4]) - int(born[:4])
            return Occasion(
                "birthday", day, (name,), f"{name}'s birthday", f"{name} turns {_number(age)}"
            )
    return None


def _number(n: int) -> str:
    return _NUMBERS[n] if 0 <= n < len(_NUMBERS) else str(n)


def spoken_list(names: Sequence[str]) -> str:
    """Names as a sentence says them: "Pat", "Pat and Lou", "Pat, Lou and Remy"."""
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"
