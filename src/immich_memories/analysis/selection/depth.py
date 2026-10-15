"""Depth inside the moments a story already shows, for a film that is still short.

The five-minute spacing keeps a burst from taking several slots, and on a dense afternoon it also
keeps every depicted moment after the first of its capture group out of the cut: a 90 s special
day with 27 usable pictures and seven depicted moments shipped four. A single moment can hold
several small interesting ones, so a film still short after every selection pass spends its free
slots here, in the story's funding order: first the depicted moments the inventory found and no
pick took, alternating between capture groups, then further frames of the chosen moments, one
round at a time: every moment's next frame before any moment's frame after that. A long moment
(36 minutes of laps on a track) can fill a short film this way (#1601); three frames a moment was
the banked ladder, never a cap on a film with slots still free. Each one is admitted only when
the look-alike check confirms it shows something new; nothing unchecked, and no refused variant,
ever fills a slot this way.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from itertools import zip_longest
from operator import attrgetter, itemgetter
from typing import Any, Protocol


class _Choice(Protocol):
    key: str
    taken: str

    @property
    def members(self) -> list[str]: ...


def _unchosen(
    ordered: Sequence[_Choice],
    used: set[str],
    group_of: Callable[[str], Any],
    held: Callable[[Any], int],
) -> Iterator[tuple[_Choice, str]]:
    """Depicted moments no pick took, alternating between capture groups, the thinnest first."""
    groups: dict[Any, list[_Choice]] = {}
    for choice in ordered:
        if choice.key not in used:
            groups.setdefault(group_of(choice.members[0]), []).append(choice)
    thinnest = sorted(groups, key=held)
    for row in zip_longest(*(groups[group] for group in thinnest)):
        yield from ((choice, choice.members[0]) for choice in row if choice is not None)


def _rungs(
    chosen: Sequence[_Choice], held: Callable[[_Choice], int]
) -> Iterator[tuple[_Choice, str]]:
    """Further members of the chosen moments, one rung at a time across every moment, the
    moment holding fewest frames first so frames admitted one at a time stay balanced."""
    chosen = sorted(chosen, key=held)
    deepest = max((len(choice.members) for choice in chosen), default=0)
    for rung in range(1, deepest):
        yield from (
            (choice, choice.members[rung]) for choice in chosen if rung < len(choice.members)
        )


def depth_ladder(
    choices: Sequence[_Choice],
    *,
    chosen: Sequence[str],
    used: set[str],
    group_of: Callable[[str], Any],
    kept: Sequence[str] = (),
) -> Iterator[tuple[_Choice, str]]:
    """The (moment, picture) pairs a short film may still spend a slot on, best first.

    `kept` is the pictures the story already carries: a capture group holding fewer of them is
    offered first, so a film deepened one frame at a time does not fill one group at a time.
    """
    ordered = sorted(choices, key=attrgetter("taken"))
    frames = Counter(group_of(asset) for asset in kept)
    yield from _unchosen(ordered, used, group_of, lambda group: frames[group])
    wanted = set(chosen)
    yield from _rungs(
        [c for c in ordered if c.key in wanted], lambda c: frames[group_of(c.members[0])]
    )


def neighbours(
    candidate: Mapping[str, Any], kept: Sequence[Mapping[str, Any]]
) -> list[Mapping[str, Any]]:
    """The kept frames a depth candidate is compared with: the nearest before and after it in
    capture time, inside its own moment and across the story.

    Comparing with every frame of its moment cost a long moment one question per frame already
    kept, and a 36-minute moment ran out of the check's bound (twice the film's slots) at six
    frames of eight (#1601). Frames are spread in time, so the nearest are the ones that could
    repeat it; the final duplicate review still reads the whole cut.
    """
    same = [k for k in kept if k.get("depicted_moment") == candidate.get("depicted_moment")]
    near = [*_nearest(candidate, same), *_nearest(candidate, kept)]
    return list({k["asset_id"]: k for k in near}.values())


def _nearest(
    candidate: Mapping[str, Any], kept: Sequence[Mapping[str, Any]]
) -> list[Mapping[str, Any]]:
    before = [k for k in kept if k["taken"] <= candidate["taken"]]
    after = [k for k in kept if k["taken"] > candidate["taken"]]
    near = [max(before, key=itemgetter("taken"))] if before else []
    return near + ([min(after, key=itemgetter("taken"))] if after else [])
