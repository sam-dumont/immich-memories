"""One place does not take a film: its frames compete with each other before the rest.

`editorial_story_threads` folds a recurring activity at one place across separate days into one
story. Its neighbouring case is one place inside one day or one stay -- the building a trip spends
its slots in -- and nothing owned it: `_Links.linked` refuses two stories that share a day,
`_by_place_and_era` needs two stories at the place, a detected trip is already one story before
the weighing, and a journey film asks no thread question at all. `editorial_story_lookalike`
refuses a picture that repeats one already kept, and a nave, a dome and a courtyard do not repeat
each other.

So the film's own proportions bound a place the way they already bound a trip. A scope is a
stretch the film funds as one thing: a journey film, or one story. Inside a scope that visited
more than one place, a place may hold as many pictures as `trip_allowance` gives a trip of the
same share of the scope -- its days, or its moments when the scope is one day. A scope of one
place is never bounded, and a bounded picture is refused onto the look-alike ledger, so it
returns when nothing else can take its slot: a stay that really is one venue still fills its film.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from itertools import chain
from typing import Any

from immich_memories.analysis.editorial_story_slots import weight_caps
from immich_memories.analysis.editorial_story_trips import trip_allowance


class PlaceShares:
    """What each place of a scope may hold, and what it holds so far."""

    def __init__(
        self,
        scope_of: Mapping[str, str],
        bounds: Mapping[tuple[str, str], int],
        scopes: Sequence[Mapping[str, Any]] = (),
        shares: Mapping[str, Mapping[str, tuple[int, int]]] | None = None,
    ) -> None:
        self._scope_of = scope_of
        self._bounds = dict(bounds)
        self._scopes = list(scopes)
        # Per scope, each place's (days or moments it holds, of the scope's whole), to size again.
        self._shares = dict(shares or {})
        self._held: Counter[tuple[str, str]] = Counter()
        self.crowded: list[dict[str, Any]] = []

    def _key(self, story_key: str, place: str) -> tuple[str, str]:
        return (self._scope_of.get(story_key, story_key), place)

    def full(self, story_key: str, place: str) -> bool:
        """Whether this place of this story already holds its share of the scope."""
        key = self._key(story_key, place)
        bound = self._bounds.get(key)
        return bound is not None and self._held[key] >= bound

    def widen(self, story_key: str, allowance: int) -> None:
        """Size this story's places for an allowance it now spends: a film still short hands its
        free slots to the moments a story already shows, and a bound sized from the story's
        weight alone (one shot for a minor story) refused every one of them (#1601). Same curve,
        larger allowance; a bound never shrinks."""
        scope = self._scope_of.get(story_key, story_key)
        for place, (at, whole) in self._shares.get(scope, {}).items():
            key = (scope, place)
            wider = trip_allowance(at, whole, allowance)
            if wider > self._bounds.get(key, 0):
                self._bounds[key] = wider
                self._scopes.append({"scope": scope, "widened_to": allowance, "place": place})

    def took(self, story_key: str, place: str) -> None:
        self._held[self._key(story_key, place)] += 1

    def gave_back(self, story_key: str, place: str) -> None:
        key = self._key(story_key, place)
        if self._held[key] > 0:
            self._held[key] -= 1

    def refused(self, story_key: str, place: str, asset: str) -> None:
        scope, _place = self._key(story_key, place)
        self.crowded.append({"scope": scope, "place": place, "asset_id": asset})

    def record(self) -> dict[str, Any]:
        return {
            "scopes": self._scopes,
            "held": [
                {"scope": scope, "place": place, "pictures": held}
                for (scope, place), held in sorted(self._held.items())
            ],
            "refused_for_their_place": self.crowded,
        }


def _allowance(story: Mapping[str, Any], slots: int) -> int:
    """What the film lets this story take: its trip reserve, or its weight's own cap."""
    return max(int(story.get("reserve") or 0), weight_caps(slots).get(story.get("weight", ""), 0))


def _spread(units: Sequence[Mapping[str, Any]], place_of: Callable[[str], str]):
    """Per place of a stretch, the days and the moments it holds."""
    days: dict[str, set[str]] = {}
    moments: dict[str, set[str]] = {}
    for unit in units:
        place = place_of(unit["asset_id"])
        if not place:
            continue
        days.setdefault(place, set()).add(str(unit.get("taken") or "")[:10])
        moments.setdefault(place, set()).add(str(unit.get("moment") or unit["asset_id"]))
    return days, moments


def _scope_shares(units, *, place_of) -> dict[str, tuple[int, int]]:
    """Per place, the days (or, on a one-day scope, the moments) it holds of the scope's whole.

    One place of a scope may hold what a trip of the same share of it may hold. A scope of one
    place is left alone: there is nothing for its pictures to compete with.
    """
    days, moments = _spread(units, place_of)
    if len(days) < 2:
        return {}
    spans_days = len(set(chain.from_iterable(days.values()))) > 1
    counted = days if spans_days else moments
    whole = len(set(chain.from_iterable(counted.values())))
    return {place: (len(at), whole) for place, at in sorted(counted.items())}


def place_shares(
    stories: Sequence[Mapping[str, Any]],
    story_units: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    place_of: Callable[[str], str],
    slots: int,
    journey: bool,
) -> PlaceShares:
    """Bound every place of every scope the film funds as one thing.

    A journey film is one scope: its stops are its stories, so a stop that took the film would
    never meet another place inside a story. Every other film scopes each story on its own.
    """
    scopes: list[tuple[str, list[str], int]] = (
        [("", [s["key"] for s in stories], slots)]
        if journey
        else [(s["key"], [s["key"]], _allowance(s, slots)) for s in stories]
    )
    scope_of: dict[str, str] = {}
    bounds: dict[tuple[str, str], int] = {}
    shares: dict[str, dict[str, tuple[int, int]]] = {}
    audit: list[dict[str, Any]] = []
    for scope, keys, allowance in scopes:
        for key in keys:
            scope_of[key] = scope
        units = [unit for key in keys for unit in story_units.get(key, ())]
        shares[scope] = _scope_shares(units, place_of=place_of)
        if allowance <= 0 or not shares[scope]:
            continue
        found = {
            place: trip_allowance(at, whole, allowance)
            for place, (at, whole) in shares[scope].items()
        }
        for place, bound in found.items():
            bounds[(scope, place)] = bound
        audit.append({"scope": scope, "allowance": allowance, "places": found})
    return PlaceShares(scope_of, bounds, audit, shares)
