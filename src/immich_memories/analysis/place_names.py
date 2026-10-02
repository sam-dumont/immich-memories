"""One place name for every surface that shows one (#1591).

Immich names a picture after the nearest GeoNames town, which can be a city district.
With `network.geocoding` on, the city, town or village OpenStreetMap names replaces it
wherever a viewer reads a place: story titles and the moment wall, location cards and map stops, captions, the saved
storyboard and the report. Code that matches or groups places (a request for a city, a day that
changes town, the usual cities) keeps Immich's `city`, which is what Immich's search answers in.

Names are resolved once, where a film's pictures arrive, through the store-cached geocoder
(one question per 1 km cell and language), and travel on the picture as `ExifInfo.place_name`.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from immich_memories.analysis.place_geocoder import locality_of, place_geocoder_for
from immich_memories.analysis.source_filter import asset_of

if TYPE_CHECKING:
    from immich_memories.analysis.place_geocoder import PlaceGeocoder
    from immich_memories.api.models import Asset, ExifInfo, VideoClipInfo
    from immich_memories.config_loader import Config


class PlaceNames:
    """The city, town or village at a coordinate when the geocoder knows one."""

    def __init__(self, geocoder: PlaceGeocoder | None) -> None:
        self._geocoder = geocoder

    def locality_at(self, latitude: float, longitude: float) -> str | None:
        if self._geocoder is None:
            return None
        return locality_of(self._geocoder.address(latitude, longitude))

    def name(self, sources: Iterable[Asset | VideoClipInfo]) -> None:
        """Give every positioned picture the place a viewer will be shown, once."""
        if self._geocoder is None:
            return
        for source in sources:
            exif = asset_of(source).exif_info
            if exif is not None and exif.latitude is not None and exif.longitude is not None:
                exif.place_name = self.locality_at(exif.latitude, exif.longitude)


def place_names_for(config: Config) -> PlaceNames:
    """The resolver this configuration allows: it asks nobody while `network.geocoding` is off."""
    return PlaceNames(place_geocoder_for(config))


def shown_city(exif: ExifInfo | None) -> str | None:
    """The city a viewer reads for a picture: its resolved locality, else Immich's name."""
    if exif is None:
        return None
    return exif.place_name or exif.city
