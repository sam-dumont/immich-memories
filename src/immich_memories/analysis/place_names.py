"""One place name for every surface that shows one (#1591).

Immich names a picture after the nearest GeoNames town, which can be a city district.
With `network.geocoding` on, OpenStreetMap's district near home or city/town/village away replaces it
wherever a viewer reads a place: story titles and the moment wall, location cards and map stops, captions, the saved
storyboard and the report. Code that matches or groups places (a request for a city, a day that
changes town, the usual cities) keeps Immich's `city`, which is what Immich's search answers in.

Names are resolved once, where a film's pictures arrive, through the store-cached geocoder
(one question per 1 km cell and language), and travel on the picture as `ExifInfo.place_name`.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from datetime import date
from typing import TYPE_CHECKING

from immich_memories.analysis.editorial_home_radius import home_of, near_home_of
from immich_memories.analysis.familiar_places import valid_coordinates
from immich_memories.analysis.place_geocoder import cell_of, locality_of, place_geocoder_for
from immich_memories.analysis.place_scope import place_groups, shared_place_name, temporal_groups
from immich_memories.analysis.source_filter import asset_of
from immich_memories.i18n_places import country_code
from immich_memories.place_names import locality_name

if TYPE_CHECKING:
    from immich_memories.analysis.place_geocoder import Address, PlaceGeocoder
    from immich_memories.api.models import Asset, ExifInfo, VideoClipInfo
    from immich_memories.config_loader import Config


Point = tuple[float | None, float | None, str | None]


class PlaceNames:
    """The district near home, or travel locality, when the geocoder knows one."""

    def __init__(
        self,
        geocoder: PlaceGeocoder | None,
        home: tuple[float, float] | None = None,
        *,
        max_gap_days: int = 2,
    ) -> None:
        self._geocoder = geocoder
        self._home = home
        self._max_gap_days = max_gap_days

    def _address(
        self, latitude: float | None, longitude: float | None, country: str | None
    ) -> Address:
        if self._geocoder is None or not valid_coordinates(latitude, longitude):
            return {}
        assert latitude is not None and longitude is not None
        address = self._geocoder.address(latitude, longitude)
        expected = country_code(country or "")
        found = address.get("country_code", "").upper()
        # A rounded cell can cross a border. Never make "Chamonix, Italy" by combining
        # one geocoder's city with the other's country; retain the source for review.
        return {} if expected and found and expected != found else address

    def _locality(
        self, address: Address, latitude: float | None, longitude: float | None
    ) -> str | None:
        if (
            latitude is not None
            and longitude is not None
            and near_home_of(self._home, [(latitude, longitude)])
        ):
            return _district_of(address) or locality_of(address)
        return locality_of(address)

    def localities_at(
        self,
        points: Iterable[tuple[float | None, float | None, str | None]],
        *,
        days: Iterable[str | None] | None = None,
    ) -> list[str | None]:
        """Use a district for a concentrated stay, or the city when captures span districts.

        Separate localities and separate visits cannot broaden one another. A district
        covering the stay uses the trip namer's existing coverage rule; excursions keep
        their own labels. Quarters, streets and POIs never become labels.
        """
        points = list(points)
        addresses = [self._address(*point) for point in points]
        labels = [
            self._locality(address, lat, lon)
            for address, (lat, lon, _) in zip(addresses, points, strict=True)
        ]
        dated = None if days is None else [_date_of(day) for day in days]
        if dated is not None and len(dated) != len(points):
            raise ValueError("Every place must have a corresponding date")
        for members in _stay_groups(points, addresses, dated, self._max_gap_days):
            for i, label in _stay_labels(members, addresses).items():
                lat, lon, _ = points[i]
                assert lat is not None and lon is not None
                if not near_home_of(self._home, [(lat, lon)]):
                    labels[i] = label
        return [locality_name(label) for label in labels]

    def name(self, sources: Iterable[Asset | VideoClipInfo]) -> None:
        """Give every positioned picture the place a viewer will be shown, once."""
        if self._geocoder is None:
            return
        positioned = [
            (exif, asset_of(source).file_created_at.date().isoformat())
            for source in sources
            if (exif := asset_of(source).exif_info) is not None
            and exif.latitude is not None
            and exif.longitude is not None
        ]
        labels = self.localities_at(
            ((e.latitude, e.longitude, e.country) for e, _ in positioned),
            days=(day for _, day in positioned),
        )
        for (exif, _), label in zip(positioned, labels, strict=True):
            exif.place_name = label


def _locality_members(points: Sequence[Point], addresses: Sequence[Address]) -> list[list[int]]:
    by_locality: dict[tuple[str, str], list[int]] = {}
    for index, (lat, lon, source_country) in enumerate(points):
        if valid_coordinates(lat, lon) and (locality := locality_of(addresses[index])):
            country = (
                addresses[index].get("country_code") or country_code(source_country or "") or ""
            )
            by_locality.setdefault((country, locality), []).append(index)
    return list(by_locality.values())


def _spatial_members(visit: list[int], points: Sequence[Point]) -> Iterator[list[int]]:
    # Many pictures share a cell. Group cells once, then expand their members.
    cells: dict[tuple[float, float], list[int]] = {}
    for i in visit:
        lat, lon, _ = points[i]
        assert lat is not None and lon is not None
        cells.setdefault(cell_of(lat, lon), []).append(i)
    coordinates = sorted(cells)
    for group in place_groups(coordinates):
        yield [i for g in group for i in cells[coordinates[g]]]


def _stay_groups(
    points: Sequence[Point],
    addresses: Sequence[Address],
    days: list[date | None] | None,
    max_gap_days: int,
) -> Iterator[list[int]]:
    for members in _locality_members(points, addresses):
        for visit in _visits(members, days, max_gap_days):
            yield from _spatial_members(visit, points)


def _district_of(address: Address) -> str | None:
    return next(
        (address[key] for key in ("suburb", "city_district", "borough") if address.get(key)), None
    )


def _date_of(day: str | None) -> date | None:
    try:
        return date.fromisoformat(day[:10]) if day else None
    except ValueError:
        return None


def _visits(
    members: list[int], days: list[date | None] | None, max_gap_days: int
) -> list[list[int]]:
    if days is None:
        return [members]
    known = {i: days[i] for i in members if days[i] is not None}
    # Missing dates establish no stay and must not join otherwise separate visits.
    return temporal_groups(list(known), lambda i: known[i] or date.min, max_gap_days) + [
        [i] for i in members if days[i] is None
    ]


def _stay_labels(members: list[int], addresses: Sequence[Address]) -> dict[int, str]:
    from immich_memories.analysis.trip_place import COVERING_SHARE

    if len(members) < 2:
        return {}
    # OSM may call one city's districts suburbs, boroughs, or city_districts. Compare
    # their names together; a missing *key* does not mean that district is unknown.
    districts = {i: _district_of(addresses[i]) for i in members}
    counts = Counter(label for label in districts.values() if label)
    if counts:
        label, count = counts.most_common(1)[0]
        # Missing district data is not evidence of a different district. Unknown members
        # retain their parent locality rather than inheriting a guessed district.
        if len(counts) == 1 or count / len(members) >= COVERING_SHARE:
            return {i: label for i in members if districts[i] == label}
    common = shared_place_name([addresses[i] for i in members], ("city", "town", "village"))
    return dict.fromkeys(members, common) if common else {}


def place_names_for(config: Config) -> PlaceNames:
    """The resolver this configuration allows: it asks nobody while `network.geocoding` is off."""
    return PlaceNames(
        place_geocoder_for(config), home_of(config.trips), max_gap_days=config.trips.max_gap_days
    )


def shown_city(exif: ExifInfo | None) -> str | None:
    """The city a viewer reads for a picture: its resolved locality, else Immich's name."""
    if exif is None:
        return None
    return exif.place_name or exif.city
