"""The stops a trip intro flies to: every one named, close ones named once.

A hike through seven villages is one area of stay, not seven destinations. Stops
are grouped with the trip-leg rule (points that stay within `CITY_SPREAD_KM` of
each other). A group of three or more becomes one stop at its middle, named by
the place its members share in the geocoder's answer (in the film's language);
without a shared level it is named "first → last". A group of one or two keeps
each town's own name. A stop nobody can name is dropped: an unlabelled dot on a
map tells the viewer nothing.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from itertools import starmap

from immich_memories.analysis.trip_detection import CITY_SPREAD_KM, haversine_km

AddressOf = Callable[[float, float], Mapping[str, str]]

# A cluster's shared name, finest first: the municipality a set of villages merged into,
# then the county, district, island and region. Never the country: it names the whole trip.
_SHARED_KEYS = ("municipality", "county", "state_district", "island", "province", "state")
# Fewer than this many close stops keep their own names; a map shows two labels fine.
_AGGREGATE_FROM = 3


@dataclass(frozen=True)
class TripStop:
    """One place the intro shows, with the name its pin carries."""

    lat: float
    lon: float
    name: str


def _groups(locations: list[tuple[float, float]]) -> list[list[int]]:
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


def _shared_name(members: list[tuple[float, float]], address_of: AddressOf | None) -> str | None:
    if address_of is None:
        return None
    addresses = list(starmap(address_of, members))
    for key in _SHARED_KEYS:
        values = {address.get(key) or None for address in addresses}
        if len(values) == 1 and (value := values.pop()):
            return value
    return None


def _fallback_name(names: list[str]) -> str | None:
    distinct = list(dict.fromkeys(name for name in names if name))
    if not distinct:
        return None
    return distinct[0] if len(distinct) == 1 else f"{distinct[0]} → {distinct[-1]}"


def group_trip_stops(
    locations: list[tuple[float, float]],
    names: list[str],
    address_of: AddressOf | None = None,
) -> list[TripStop]:
    """The intro's stops, in the order the trip first reaches them.

    `names` is index-aligned with `locations` ("" where unknown). `address_of` is the
    geocoder's administrative answer for a point; it is asked only about members of a
    group large enough to share one name.
    """
    stops: list[TripStop] = []
    for group in _groups(locations):
        members = [locations[i] for i in group]
        member_names = [names[i] if i < len(names) else "" for i in group]
        if len(group) < _AGGREGATE_FROM:
            stops.extend(
                TripStop(lat, lon, name)
                for (lat, lon), name in zip(members, member_names, strict=True)
                if name
            )
            continue
        name = _shared_name(members, address_of) or _fallback_name(member_names)
        if name:
            lat = sum(lat for lat, _ in members) / len(members)
            lon = sum(lon for _, lon in members) / len(members)
            stops.append(TripStop(lat, lon, name))
    return stops
