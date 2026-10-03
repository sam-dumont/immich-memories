"""The geographic groups and shared address names used by map stops and clip labels.

Extracted from titles.trip_stops so captions use the existing trip geography rule.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date
from typing import TypeVar

T = TypeVar("T")


def temporal_groups(
    items: Sequence[T], day_of: Callable[[T], date], max_gap_days: int
) -> list[list[T]]:
    """The trip detector's calendar-gap rule, also used to keep separate visits apart."""
    groups: list[list[T]] = []
    for item in sorted(items, key=day_of):
        if groups and (day_of(item) - day_of(groups[-1][-1])).days <= max_gap_days:
            groups[-1].append(item)
        else:
            groups.append([item])
    return groups


def place_groups(locations: Sequence[tuple[float, float]]) -> list[list[int]]:
    """Group positions that all lie within the trip planner's city spread of each other."""
    # Import here: trip detection reads resolved names, which also use this grouping.
    from immich_memories.analysis.trip_detection import CITY_SPREAD_KM, haversine_km

    groups: list[list[int]] = []
    for index, (lat, lon) in enumerate(locations):
        home = next(
            (
                group
                for group in groups
                if all(
                    haversine_km(lat, lon, *locations[member]) <= CITY_SPREAD_KM for member in group
                )
            ),
            None,
        )
        if home is None:
            groups.append([index])
        else:
            home.append(index)
    return groups


def shared_place_name(addresses: Sequence[Mapping[str, str]], keys: Sequence[str]) -> str | None:
    """The first allowed address level every member shares, or no supported common place."""
    countries = {address["country_code"] for address in addresses if address.get("country_code")}
    if len(countries) > 1:
        return None
    for key in keys:
        values = {address.get(key) or None for address in addresses}
        if len(values) == 1 and (value := values.pop()):
            return value
    return None
