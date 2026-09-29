"""Where a trip changes where it stays, it becomes two legs.

A hike from village to village followed by four days in a city is two chapters: judged as
one story, the hike's favourites took every slot and the city got none. Legs are found from
geography, not place names (village-level geocoding flips between neighbours on a day trip):

- a day's position is the median of its pictures' coordinates;
- consecutive days form an area while each lies within `area_km` of the area's median
  (the spread trip detection already calls one city);
- an area of `MIN_LEG_DAYS` or more is a leg; a shorter one (a travel day, a one-night stop)
  joins the leg before it, or the first leg when nothing precedes it;
- a trip splits only when two legs lie more than `AWAY_FROM_HOME_KM` apart.

So a road trip that never stays three days anywhere is one leg, one stay with day trips is
one leg, and a hike followed by a city is two. Measured on three real trips before building
(#1563): only the hike-then-city trip split, at every radius from 15 to 40 km.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from itertools import pairwise
from statistics import median

from immich_memories.analysis.trip_detection import (
    AWAY_FROM_HOME_KM,
    CITY_SPREAD_KM,
    haversine_km,
)

MIN_LEG_DAYS = 3

Point = tuple[float, float]


def legs_of_days(
    points_by_day: Mapping[str, Sequence[Point]], *, area_km: float = CITY_SPREAD_KM
) -> dict[str, int]:
    """The leg (0, 1, ...) each ISO day belongs to; every day is 0 when the trip does not split.

    A day without positions belongs to the leg of the positioned day before it.
    """
    days = sorted(points_by_day)
    placed = {d: _median(points_by_day[d]) for d in days if points_by_day[d]}
    areas = _areas([d for d in days if d in placed], placed, area_km)
    legs = _legs(areas)
    if len(legs) < 2 or any(
        haversine_km(*_centre(a, placed), *_centre(b, placed)) <= AWAY_FROM_HOME_KM
        for a, b in pairwise(legs)
    ):
        return dict.fromkeys(days, 0)
    leg_of = {day: index for index, leg in enumerate(legs) for day in leg}
    out: dict[str, int] = {}
    current = 0
    for day in days:
        current = leg_of.get(day, current)
        out[day] = current
    return out


def _areas(days: list[str], placed: Mapping[str, Point], area_km: float) -> list[list[str]]:
    areas: list[list[str]] = []
    for day in days:
        if areas and haversine_km(*_centre(areas[-1], placed), *placed[day]) <= area_km:
            areas[-1].append(day)
        else:
            areas.append([day])
    return areas


def _legs(areas: list[list[str]]) -> list[list[str]]:
    """Areas long enough to be legs, each short area joined to the leg before it."""
    legs: list[list[str]] = []
    pending: list[str] = []
    for area in areas:
        if len(area) >= MIN_LEG_DAYS:
            legs.append(pending + area if not legs else area)
            pending = []
        elif legs:
            legs[-1].extend(area)
        else:
            pending.extend(area)
    return legs


def _centre(days: Sequence[str], placed: Mapping[str, Point]) -> Point:
    return _median([placed[d] for d in days])


def _median(points: Sequence[Point]) -> Point:
    return median(p[0] for p in points), median(p[1] for p in points)
