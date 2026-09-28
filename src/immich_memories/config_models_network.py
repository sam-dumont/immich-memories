"""The outside hosts a run may contact, none of them by default.

A default run reaches the user's Immich server, the endpoints the user wrote
down themselves, and nothing else. Each switch here buys back one third-party
host, and every one of them learns something about where the pictures were
taken.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# Named here so the docs, the preflight rows and the code cannot drift apart.
GEOCODING_HOST = "nominatim.openstreetmap.org"
MAP_TILE_HOST = "server.arcgisonline.com"


class NetworkConfig(BaseModel):
    """Third-party hosts this install is allowed to reach."""

    geocoding: bool = Field(
        default=False,
        description=(
            f"Reverse geocode through {GEOCODING_HOST}: the right district's name where "
            "Immich names a neighbouring town, better trip names, and place names in the "
            "film's language. Sends each trip centroid and the coordinates of the places "
            "on the cut, rounded to about a kilometre, once per place"
        ),
    )
    geocoding_url: str = Field(
        default="",
        description=(
            "A self-hosted Nominatim to ask instead of the public one "
            "(e.g. http://nominatim.lan:8080). Only read when geocoding is on"
        ),
    )
    map_tiles: bool = Field(
        default=False,
        description=(
            f"Fetch satellite tiles from {MAP_TILE_HOST}: the trip fly-over, the static "
            "trip map and the map behind location cards. Sends tile coordinates covering "
            "the trip area and the home base"
        ),
    )
