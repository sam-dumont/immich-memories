"""Days whose own words stand out from their year, proposed to the day check.

Nothing here asks the library a question. A race day writes "race track" and "Ferrari" about
dozens of its pictures and the rest of the year never does; a cat or a baby is written about
every week, so the year's own spread cancels it out, with no list of words to skip and no list
of occasions to look for. What stands out is only a proposal: the day check still judges it.

Measured on three years of a real library, 7 to 12 of about 300 candidate days a year stand out
this way: races, concerts, birthdays, a birth, a light festival. A small reader comparing a
month's lines missed several of them, and which ones it missed changed with the prompt's wording.
"""

from __future__ import annotations

import collections
import re
from collections.abc import Iterable, Mapping
from datetime import date
from typing import Any

_WORD = re.compile(r"[a-z]{4,}")
# A word has to be written about this many of the day's pictures to be the day's, not a detail.
_REPEATED = 10
# And written on at most this share of the year's described days. Standing out needs a year to
# stand out from: under 34 described days nothing is rare, and the month reading works alone.
_RARE_SHARE = 0.03
# One repeated rare word is mostly how a day was written about ("cute", "length", "leather": 20
# such days in a measured year, three of them occasions); a day needs two.
_WORDS_OF_A_DAY = 2
# Pictures sent by someone else or saved tell what happened, less surely than the day's own.
_FORWARDED_WEIGHT = 0.5
_NAMED = 3


def distinctive_days(
    said: Mapping[date, list[str]],
    candidates: Iterable[date],
    *,
    forwarded: Mapping[date, list[str]] | None = None,
) -> dict[date, str]:
    """The candidate days whose words stand out from the year, each with the words that do.

    `said` holds what was written about each day's own pictures, for every described day of
    the year: the year is what a day stands out from. Forwarded captions count for half and
    only on a day the camera already made.
    """
    days_saying, rare = _year_of(said)
    proposed: dict[date, str] = {}
    for day in sorted(candidates):
        written = _written(said.get(day, []), (forwarded or {}).get(day, []))
        standing = [
            surface
            for word, (count, surface) in written.items()
            if count >= _REPEATED and days_saying[word] <= rare
        ]
        if len(standing) >= _WORDS_OF_A_DAY:
            proposed[day] = ", ".join(standing[:_NAMED])
    return proposed


def telling(
    pictures: list, captions: Mapping[str, str], said: Mapping[date, list[str]], *, keep: int
) -> list:
    """The described pictures whose captions say most of what the year does not, most first.

    A trail race's 112 forwarded pictures, three of them picked by the hour, were a couple
    jogging through a forest; its obstacle course and finish line went unread.
    """
    days_saying, rare = _year_of(said)

    def rarity(picture: Any) -> int:
        return sum(1 for word in _spelled(captions[picture.id]) if days_saying[word] <= rare)

    described = [picture for picture in pictures if captions.get(picture.id)]
    return sorted(described, key=rarity, reverse=True)[:keep]


def _year_of(said: Mapping[date, list[str]]) -> tuple[collections.Counter[str], float]:
    """On how many of the year's described days each word was written, and how few is rare."""
    days_saying = collections.Counter(word for texts in said.values() for word in _words(texts))
    return days_saying, _RARE_SHARE * len(said)


def _written(own: list[str], sent: list[str]) -> dict[str, tuple[float, str]]:
    """Each word of the day: on how many of its pictures it was written, and how it was spelled."""
    counts: dict[str, float] = collections.defaultdict(float)
    spelled: dict[str, str] = {}
    for weight, texts in ((1.0, own), (_FORWARDED_WEIGHT, sent)):
        for text in texts:
            for word, surface in _spelled(text).items():
                counts[word] += weight
                spelled.setdefault(word, surface)
    return {
        word: (counts[word], spelled[word])
        for word in sorted(counts, key=counts.__getitem__, reverse=True)
    }


def _words(texts: list[str]) -> set[str]:
    return {word for text in texts for word in _spelled(text)}


def _spelled(text: str) -> dict[str, str]:
    """A caption's words, a plural read as its singular, each with the spelling it had."""
    return {surface.removesuffix("s"): surface for surface in _WORD.findall(text.lower())}
