"""Administrative place names from Nominatim, asked once per place and kept in the store.

Immich names every picture after the nearest GeoNames town of 500 people or more, so a
district that is not a municipality of its own (Wilrijk, inside Antwerp) is named after
whichever neighbour's point is closest (Hoboken, Edegem). OpenStreetMap carries the parent city.

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
from immich_memories.tracking.report_context import private_place_name

if TYPE_CHECKING:
    from immich_memories.config_loader import Config

logger = logging.getLogger(__name__)

Address = dict[str, str]
Fetch = Callable[[float, float], "Address | None"]

# About 1.1 km at the equator: nearby pictures share a question; no exact GPS is sent.
_PRECISION = 2
# Zoom 14 selects settlement nodes: in Laeken it returns nearby Mutsaard. Street-level
# lookup carries the containing suburb instead. We still send rounded GPS and keep only
# administrative names, never the street itself.
_DISTRICT_ZOOM = 16
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
# A visit to Berlin stays Berlin across its districts. Rural settlements keep their own
# names before the wider municipality; suburbs and quarters never replace a known town.
_LOCALITY_KEYS = (
    "city",
    "village",
    "town",
    "hamlet",
    "municipality",
)
_USER_AGENT = f"immich-memories/{__version__} (+https://github.com/sam-dumont/immich-memories)"


def cell_of(latitude: float, longitude: float) -> tuple[float, float]:
    """The rounded coordinate that is sent and cached in place of the picture's own."""
    return round(latitude, _PRECISION), round(longitude, _PRECISION)


@private_place_name
def locality_of(address: Address) -> str | None:
    """The city, town or village an address is in; None when only finer labels are known."""
    return next((address[key] for key in _LOCALITY_KEYS if address.get(key)), None)


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


def accept_language_chain(language: str) -> str:
    """Nominatim's `accept-language` value: the film's language, then its base language.

    No "en" is appended (#1954): a place with no translation in either must keep its
    own native name, never English boilerplate ("Municipality of Platanias" in a
    French film). Nominatim already falls back to its own `name` tag on its own once
    nothing in the requested list is available -- that fallback is not a header this
    code sends, it is what happens when the sent list runs out.
    """
    return ",".join(dict.fromkeys((language, language.split("-")[0])))


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
    geolocator = Nominatim(user_agent=_USER_AGENT, domain=domain, scheme=scheme, timeout=10)
    # Let PlaceGeocoder distinguish outages from genuine empty answers. The limiter's
    # default swallows errors as None, which otherwise poisons the persistent cache.
    reverse = RateLimiter(
        geolocator.reverse, min_delay_seconds=1, max_retries=0, swallow_exceptions=False
    )

    def fetch(latitude: float, longitude: float) -> Address | None:
        languages = accept_language_chain(language)
        location = reverse(f"{latitude}, {longitude}", zoom=_DISTRICT_ZOOM, language=languages)
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
        # Old zoom/language-policy answers must not mask the corrected query. The "en"
        # cache key from #1947 is deliberately abandoned, not renamed: those cells cached
        # an English fallback answer that #1954 removed, and must be asked again rather
        # than reused, with the film's own accept-language chain (never "en").
        cell = f"z{_DISTRICT_ZOOM}-film:{latitude:.{_PRECISION}f},{longitude:.{_PRECISION}f}"
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
