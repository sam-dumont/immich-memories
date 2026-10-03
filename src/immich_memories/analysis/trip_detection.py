"""Trip detection: GPS clustering, overnight stops, home base identification."""

from __future__ import annotations

import logging
import math
import operator
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING

from immich_memories.analysis.place_scope import place_groups, temporal_groups
from immich_memories.analysis.trip_place import COVERING_SHARE, TripPlace, trip_place
from immich_memories.api.models import Asset
from immich_memories.place_names import short_place_name
from immich_memories.tracking.report_context import private_place_name

if TYPE_CHECKING:
    from immich_memories.analysis.place_geocoder import PlaceGeocoder
    from immich_memories.analysis.place_names import PlaceNames
    from immich_memories.config_loader import Config

logger = logging.getLogger(__name__)

# (latitude, longitude, spread_km) -> a place name, or None when it has none.
Geocoder = Callable[..., "str | None"]

# The scales a single reverse-geocoded point can name.
_GEOCODER_SCALES = frozenset({"city", "region"})


@dataclass
class DetectedTrip:
    """A detected trip: a cluster of GPS-tagged assets far from home."""

    start_date: date
    end_date: date
    location_name: str
    asset_count: int
    centroid_lat: float
    centroid_lon: float
    asset_ids: list[str] = field(default_factory=list)
    # The scale the name was chosen at: see TripPlace.scale.
    location_kind: str = ""


# Pictures closer to home than this are home, not a trip; a location card never names them.
AWAY_FROM_HOME_KM = 50.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compute great-circle distance between two GPS points in kilometers."""
    r = 6371.0  # Earth radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(a))


def _filter_away_assets(
    assets: list[Asset], home_lat: float, home_lon: float, min_km: float
) -> list[Asset]:
    away = []
    for a in assets:
        if a.exif_info is None or a.exif_info.latitude is None or a.exif_info.longitude is None:
            continue
        if haversine_km(home_lat, home_lon, a.exif_info.latitude, a.exif_info.longitude) >= min_km:
            away.append(a)
    return away


def _group_by_temporal_gaps(away: list[Asset], max_gap_days: int) -> list[list[Asset]]:
    return temporal_groups(away, lambda asset: asset.file_created_at.date(), max_gap_days)


def _build_trip_from_group(
    group: list[Asset], *, name_locations: bool = True, geocoder: Geocoder | None = None
) -> DetectedTrip:
    lats = [a.exif_info.latitude for a in group if a.exif_info and a.exif_info.latitude]
    lons = [a.exif_info.longitude for a in group if a.exif_info and a.exif_info.longitude]
    c_lat = sum(lats) / len(lats) if lats else 0.0
    c_lon = sum(lons) / len(lons) if lons else 0.0
    place = _derive_location_name(group, c_lat, c_lon, geocoder) if name_locations else None
    return DetectedTrip(
        start_date=group[0].file_created_at.date(),
        end_date=group[-1].file_created_at.date(),
        location_name=place.name if place else "",
        location_kind=place.scale if place else "",
        asset_count=len(group),
        centroid_lat=c_lat,
        centroid_lon=c_lon,
        asset_ids=[a.id for a in group],
    )


def detect_trips(
    assets: list[Asset],
    home_lat: float,
    home_lon: float,
    min_distance_km: float = AWAY_FROM_HOME_KM,
    min_duration_days: int = 2,
    max_gap_days: int = 2,
    *,
    name_locations: bool = True,
    geocoder: Geocoder | None = None,
) -> list[DetectedTrip]:
    """Detect trips: filter GPS assets far from home, group by temporal gaps, filter by duration.

    Without a geocoder every trip is named from the EXIF its own pictures carry,
    which is what a default install does: no coordinate leaves the machine.
    `geocoder_for` builds one when the config allows it.

    name_locations=False skips the naming entirely. A caller that only wants the
    dates — the special-day scan, which uses trips solely to know which days to
    skip — otherwise pays for a name per trip across every year it walks, and
    throws every answer away.
    """
    away = _filter_away_assets(assets, home_lat, home_lon, min_distance_km)
    if not away:
        return []
    away.sort(key=lambda a: a.file_created_at)
    groups = _group_by_temporal_gaps(away, max_gap_days)

    trips: list[DetectedTrip] = []
    for group in groups:
        span_days = (group[-1].file_created_at.date() - group[0].file_created_at.date()).days
        if span_days >= min_duration_days:
            trips.append(
                _build_trip_from_group(group, name_locations=name_locations, geocoder=geocoder)
            )
    return trips


_HomeBase = tuple[float, float, str, set[date]]
_DailyStop = tuple[date, float, float, str, list[str]]


def geocoder_for(config: Config) -> Geocoder | None:
    """The trip namer this configuration allows, or None for names from the pictures' EXIF.

    `network.geocoding` is off by default. When it is on, every centroid goes through the
    shared place geocoder: rounded, rate limited, answered in the film's language, and kept in
    the store, so the next scan of the same year asks nobody.
    """
    from immich_memories.analysis.editorial_home_radius import home_of
    from immich_memories.analysis.place_geocoder import place_geocoder_for
    from immich_memories.analysis.place_names import PlaceNames

    places = place_geocoder_for(config)
    if places is None:
        return None

    return _TripGeocoder(
        places, PlaceNames(places, home_of(config.trips), max_gap_days=config.trips.max_gap_days)
    )


class _TripGeocoder:
    """Discovery shares the film's locality resolver when a trip fits a local stay."""

    def __init__(self, places: PlaceGeocoder, names: PlaceNames) -> None:
        self.places = places
        self.names = names

    def __call__(self, lat: float, lon: float, spread_km: float | None = None) -> str | None:
        return trip_place_name(self.places.address(lat, lon), spread_km)

    def local_place(self, assets: list[Asset], *, local_stay: bool) -> TripPlace | None:
        # Discovery is read-only: another call may use the same assets with geocoding off
        # or a different language. Only copy the EXIF that the resolver will annotate.
        named = [
            asset.model_copy(update={"exif_info": asset.exif_info.model_copy()})
            if asset.exif_info is not None
            else asset
            for asset in assets
        ]
        self.names.name(named)
        return trip_place(named, local_stay=local_stay)


# Below this spread a trip fits one town, and the geocoder names the town.
CITY_SPREAD_KM = 25.0
# The village before the town or city it belongs to: in a merged municipality the village is
# where the trip went. Never a district: a week in Barcelona is not a week in Gràcia.
_CITY_KEYS = ("village", "town", "city")
# Never "county": in some countries it is a regional unit with no name in the
# film's language ("Περιφερειακή Ενότητα Ρεθύμνης" for a Crete trip).
_REGION_KEYS = ("island", "state", "state_district", "province")


def _place_at_scale(address: Mapping[str, str], spread_km: float | None) -> str | None:
    keys: tuple[str, ...] = _REGION_KEYS
    if spread_km is not None and spread_km < CITY_SPREAD_KM:
        keys = _CITY_KEYS + _REGION_KEYS
    return next((name for key in keys if (name := short_place_name(address.get(key)))), None)


@private_place_name
def trip_place_name(address: Mapping[str, str], spread_km: float | None = None) -> str | None:
    """The trip's place at its scale: the town under `CITY_SPREAD_KM`, else the region.

    None when the address has no country or no place at that scale, so the trip keeps the
    name its own pictures give it.
    """
    country = address.get("country")
    place = _place_at_scale(address, spread_km)
    if not (place and country):
        return None
    return country if place == country else f"{place}, {country}"


def _compute_spread_km(assets: list[Asset]) -> float:
    """Approximate max GPS spread via bounding-box extremes (O(n) vs O(n²))."""
    coords = [
        (a.exif_info.latitude, a.exif_info.longitude)
        for a in assets
        if a.exif_info and a.exif_info.latitude and a.exif_info.longitude
    ]
    if len(coords) < 2:
        return 0.0
    extremes = [
        min(coords, key=operator.itemgetter(0)),
        max(coords, key=operator.itemgetter(0)),
        min(coords, key=operator.itemgetter(1)),
        max(coords, key=operator.itemgetter(1)),
    ]
    max_dist = 0.0
    for i, (lat1, lon1) in enumerate(extremes):
        for lat2, lon2 in extremes[i + 1 :]:
            d = haversine_km(lat1, lon1, lat2, lon2)
            if d > max_dist:
                max_dist = d
    return max_dist


def _derive_location_name(
    assets: list[Asset],
    centroid_lat: float | None = None,
    centroid_lon: float | None = None,
    geocoder: Geocoder | None = None,
) -> TripPlace:
    """The trip's name at the scale its pictures cover (see `trip_place`).

    An allowed geocoder only speaks where one point can: a trip that fits a
    city or a region. It knows the film's language, which is what it buys;
    an island, two regions or a country come from the pictures themselves.
    """
    spread_km = _compute_spread_km(assets)
    local_stay = spread_km < CITY_SPREAD_KM or _has_local_core(assets)
    place = trip_place(assets, local_stay=local_stay)
    if place is not None and place.scale == "city" and isinstance(geocoder, _TripGeocoder):
        # Resolve the source window, not just the centroid or the eventual selected clips.
        # Island/region/country trips need no per-photo requests during discovery.
        return geocoder.local_place(assets, local_stay=local_stay) or place
    geocodable = _centroid_can_name(place, assets, spread_km)
    if (
        geocodable
        and geocoder is not None
        and centroid_lat is not None
        and centroid_lon is not None
        and (geocoded := geocoder(centroid_lat, centroid_lon, spread_km=spread_km))
    ):
        return TripPlace(geocoded, "city" if spread_km < CITY_SPREAD_KM else "region")
    if place is not None:
        return place
    cities = Counter(a.exif_info.city for a in assets if a.exif_info and a.exif_info.city)
    return TripPlace(cities.most_common(1)[0][0] if cities else "Unknown Location", "city")


def _centroid_can_name(place: TripPlace | None, assets: list[Asset], spread_km: float) -> bool:
    # A city supported by the pictures survives distant excursions. Asking the centroid
    # at regional scale would overwrite that evidence with an unrelated broader label.
    # Resolved captions already carry the chosen locality; do not replace their district
    # with the town above it during a second lookup.
    if place is not None and place.scale == "city":
        return spread_km < CITY_SPREAD_KM and not any(
            asset.exif_info and asset.exif_info.place_name for asset in assets
        )
    return place is None or place.scale in _GEOCODER_SCALES


def _has_local_core(assets: list[Asset]) -> bool:
    """A stay may have excursions: use the existing map groups and trip coverage rule."""
    from immich_memories.analysis.place_geocoder import cell_of

    cells = Counter(
        cell_of(exif.latitude, exif.longitude)
        for asset in assets
        if (exif := asset.exif_info) is not None
        and exif.latitude is not None
        and exif.longitude is not None
    )
    coordinates = sorted(cells)
    total = sum(cells.values())
    return any(
        sum(cells[coordinates[i]] for i in group) / total >= COVERING_SHARE
        for group in place_groups(coordinates)
    )
