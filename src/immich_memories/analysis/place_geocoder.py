"""District-level place names from Nominatim, asked once per place and kept in the store.

Immich names every picture after the nearest GeoNames town of 500 people or more, so a
district that is not a municipality of its own (Wilrijk, inside Antwerp) is named after
whichever neighbour's point is closest (Hoboken, Edegem). OpenStreetMap knows the district.

This is opt-in (`network.geocoding`): with it off nothing here is built and no coordinate
leaves the host. With it on, each coordinate is rounded to two decimals (about a kilometre)
before it is sent, and the answer is kept per rounded cell and language in the store, so a
library is asked about once, not once per render. Nominatim's usage policy is one request a
second with an identifying User-Agent; a self-hosted Nominatim takes the same requests.
Anything that fails leaves Immich's own name in place: a film is never held up by a geocoder.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import sqlalchemy as sa

from immich_memories._version import __version__
from immich_memories.config_models_network import GEOCODING_HOST
from immich_memories.db import Store, now_db
from immich_memories.db.tables import geocoded_places
from immich_memories.db.upsert import upsert

if TYPE_CHECKING:
    from immich_memories.config_loader import Config

logger = logging.getLogger(__name__)

Address = dict[str, str]
Fetch = Callable[[float, float], "Address | None"]

# About 1.1 km at the equator: fine enough to tell two districts apart, coarse enough that a
# day's pictures share one question and no house number is ever in the request.
_PRECISION = 2
# Nominatim zoom 14 answers at suburb level, and its address carries every level above it:
# district, town, municipality, region, country. One question serves a caption and a trip.
_DISTRICT_ZOOM = 14
# What is kept of an answer. Anything finer (road, house number, postcode) is dropped.
_ADMINISTRATIVE = frozenset(
    {
        "quarter",
        "suburb",
        "city_district",
        "borough",
        "hamlet",
        "village",
        "town",
        "city",
        "municipality",
        "island",
        "state_district",
        "state",
        "province",
        "county",
        "country",
        "country_code",
    }
)
# The finest name a viewer recognises as a place: a district, then the village or town, then
# the city. "quarter" is left out on purpose: it names a block ("Le Marais"), not a district.
_DISTRICT_KEYS = (
    "suburb",
    "city_district",
    "borough",
    "village",
    "town",
    "hamlet",
    "city",
    "municipality",
)
_USER_AGENT = (
    f"immich-memories/{__version__} (+https://github.com/sam-dumont/immich-video-memory-generator)"
)


def cell_of(latitude: float, longitude: float) -> tuple[float, float]:
    """The rounded coordinate that is sent and cached in place of the picture's own."""
    return round(latitude, _PRECISION), round(longitude, _PRECISION)


def district_of(address: Address) -> str | None:
    """The district, village or town an address is in; None when it names none."""
    return next((address[key] for key in _DISTRICT_KEYS if address.get(key)), None)


def place_geocoder_for(config: Config) -> PlaceGeocoder | None:
    """The geocoder this configuration allows, or None: `network.geocoding` is off by default.

    It answers in the film's caption language, the one every place name on screen is in.

    Returning None rather than a geocoder that answers nothing keeps the outside call out of
    the code path instead of inside a branch of it.
    """
    if not config.network.geocoding:
        return None
    from immich_memories.db import open_store
    from immich_memories.processing.clip_caption import resolve_caption_locale

    language = resolve_caption_locale(config.title_screens.locale)
    fetch = nominatim_fetch(language, config.network.geocoding_url)
    return PlaceGeocoder(open_store(config), language, fetch)


def nominatim_fetch(language: str, url: str = "") -> Fetch:
    """The rate-limited reverse geocoder, answering in `language`.

    `url` is a self-hosted Nominatim (`http://nominatim.lan:8080`); empty means the public
    OpenStreetMap service. Built only once the caller has decided geocoding is allowed.
    """
    from geopy.extra.rate_limiter import RateLimiter
    from geopy.geocoders import Nominatim

    parts = urlsplit(url.strip()) if url.strip() else None
    domain = f"{parts.netloc}{parts.path}".rstrip("/") if parts else GEOCODING_HOST
    scheme = parts.scheme if parts and parts.scheme else "https"
    geolocator = Nominatim(user_agent=_USER_AGENT, domain=domain, scheme=scheme)
    reverse = RateLimiter(geolocator.reverse, min_delay_seconds=1)

    def fetch(latitude: float, longitude: float) -> Address | None:
        location = reverse(f"{latitude}, {longitude}", zoom=_DISTRICT_ZOOM, language=language)
        if location is None:
            return None
        address = location.raw.get("address", {})
        return {
            key: value
            for key, value in address.items()
            if key in _ADMINISTRATIVE and isinstance(value, str)
        }

    return fetch


class PlaceGeocoder:
    """Administrative names around a coordinate, by rounded cell and language.

    `fetch` is the one outside call. An answer, including "nothing here", is written to the
    store as soon as it arrives; an error is not, and stops this instance asking, so an
    outage costs one failed call rather than one per place.
    """

    def __init__(self, store: Store, language: str, fetch: Fetch) -> None:
        self._store = store
        self._language = language
        self._fetch: Fetch | None = fetch

    def address(self, latitude: float, longitude: float) -> Address:
        """The names around this point, `{}` when nobody can say."""
        latitude, longitude = cell_of(latitude, longitude)
        cell = f"{latitude:.{_PRECISION}f},{longitude:.{_PRECISION}f}"
        with self._store.connect() as connection:
            known = connection.execute(
                sa.select(geocoded_places.c.address).where(
                    geocoded_places.c.cell == cell,
                    geocoded_places.c.language == self._language,
                )
            ).scalar_one_or_none()
        if known is not None:
            return dict(known)
        if self._fetch is None:
            return {}
        try:
            answer = self._fetch(latitude, longitude) or {}
        except Exception as error:  # noqa: BLE001
            # WHY so broad: geopy raises its own hierarchy, and only part of it inherits from
            # OSError. A geocoder that is down, rate limiting or refusing must cost the film
            # its better names, never the film.
            logger.info("Reverse geocoding unavailable (%s); keeping Immich's names", error)
            self._fetch = None
            return {}
        with self._store.begin() as connection:
            upsert(
                connection,
                geocoded_places,
                [
                    {
                        "cell": cell,
                        "language": self._language,
                        "address": answer,
                        "fetched_at": now_db(),
                    }
                ],
                ("cell", "language"),
            )
        return answer
