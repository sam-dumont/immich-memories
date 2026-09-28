"""The country a library lives in: where its home base is, as Immich's own geodata places it.

Holidays move by country, and the home base already says where home is. Immich answers where
a coordinate lies from the geodata it ships, so asking it stays inside the library's own server.
"""

from __future__ import annotations

import functools
import logging
import re
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from immich_memories.config_loader import Config

logger = logging.getLogger(__name__)

# The holiday dates a library had before its home base said where it was.
_WITHOUT_A_HOME = "US"


def country_code(name: str | None) -> str | None:
    """The ISO 3166 code of a country as Immich names it, or None when the name is unknown.

    Read against the ``holidays`` library's own registry, so a code it returns is one the
    library keeps a calendar for.
    """
    if not name:
        return None
    from holidays.registry import COUNTRIES

    key = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_").removeprefix("the_")
    entry = COUNTRIES.get(key)
    return entry[1] if entry else None


def home_country(config: Config) -> str:
    """The ISO code of the country the home base is in, or the US when there is no home base
    or Immich cannot say."""
    trips = config.trips
    if trips.homebase_latitude == trips.homebase_longitude == 0.0:
        return _WITHOUT_A_HOME
    found = _country_at(
        config.immich.url, config.immich.api_key, trips.homebase_latitude, trips.homebase_longitude
    )
    return found or _WITHOUT_A_HOME


@functools.lru_cache(maxsize=8)
def _country_at(url: str, api_key: str, lat: float, lon: float) -> str | None:
    try:
        response = httpx.get(
            f"{url.rstrip('/')}/api/map/reverse-geocode",
            params={"lat": lat, "lon": lon},
            headers={"x-api-key": api_key},
            timeout=10.0,
        )
        response.raise_for_status()
        rows = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Immich could not say which country the home base is in (%s)", exc)
        return None
    first = rows[0] if isinstance(rows, list) and rows else {}
    name = first.get("country") if isinstance(first, dict) else None
    code = country_code(name)
    if code is None:
        logger.warning("No holiday calendar is known for %r; using the US holidays", name)
    return code
