"""Where the owner lived, and since when, read from where the library's pictures were taken.

The configured home base is one point for all time; a library that spans a move needs the
home of each picture's own time ("the farthest I have been from home" is measured from the
home the owner had then). Each year, the ~200 m cell photographed on the most days is home
when it holds at least ten of them and a fifth of that year's photographed days; a new home
starts when that cell moves more than 300 m, on its first photographed day.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from immich_memories.analysis.familiar_places import valid_coordinates
from immich_memories.analysis.trip_detection import haversine_km
from immich_memories.free_text.library import LibraryPicture

_CELL_DEGREES = 0.002
_MOVED_KM = 0.3
_MIN_HOME_DAYS = 10
_MIN_HOME_SHARE = 0.2

_Cell = tuple[int, int]
_Point = tuple[float, float]


@dataclass(frozen=True, slots=True)
class Home:
    """One home and the days it was home: `since` None is from the start, `until` None is now."""

    latitude: float
    longitude: float
    since: date | None
    until: date | None


def homes_over_time(
    pictures: Iterable[LibraryPicture], configured: _Point | None = None
) -> tuple[Home, ...]:
    """The homes the pictures show, oldest first; the configured home base when they show none."""
    days: dict[int, dict[_Cell, set[date]]] = defaultdict(lambda: defaultdict(set))
    points: dict[_Cell, list[_Point]] = defaultdict(list)
    for picture in pictures:
        if picture.latitude is None or picture.longitude is None:
            continue
        if not valid_coordinates(picture.latitude, picture.longitude):
            continue
        cell = (round(picture.latitude / _CELL_DEGREES), round(picture.longitude / _CELL_DEGREES))
        day = picture.taken_at.date()
        days[day.year][cell].add(day)
        points[cell].append((picture.latitude, picture.longitude))
    found: list[tuple[_Point, date]] = []
    for year in sorted(days):
        cell, held = max(days[year].items(), key=lambda item: (len(item[1]), item[0]))
        pictured = set().union(*days[year].values())
        if len(held) < max(_MIN_HOME_DAYS, _MIN_HOME_SHARE * len(pictured)):
            continue
        where = _middle(points[cell])
        if not found or haversine_km(*found[-1][0], *where) > _MOVED_KM:
            found.append((where, min(held)))
    if not found:
        return (Home(*configured, since=None, until=None),) if configured else ()
    return tuple(
        Home(
            latitude=where[0],
            longitude=where[1],
            since=since if index else None,
            until=found[index + 1][1] if index + 1 < len(found) else None,
        )
        for index, (where, since) in enumerate(found)
    )


def _middle(points: Sequence[_Point]) -> _Point:
    latitudes = sorted(point[0] for point in points)
    longitudes = sorted(point[1] for point in points)
    return latitudes[len(latitudes) // 2], longitudes[len(longitudes) // 2]
