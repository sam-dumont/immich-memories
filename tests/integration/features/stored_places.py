"""The places the Immich under test stored on the fixture's pictures, read back from it.

The fixture names its places through OpenStreetMap; a real Immich names each after its own
nearest GeoNames town. A test about a name the app reads off Immich's places (a trip's, a
special day's) asks the server it runs against what it stored, so it holds on both.
"""

from __future__ import annotations

from collections import Counter

import httpx

from tests.e2e.fake_library import ALL_PICTURES
from tests.integration.features.immich_server import LibraryServer


def stored_places(immich: LibraryServer, first_day: str, last_day: str) -> list[tuple[str, str]]:
    """(town, country) Immich stored on each located picture of these days, in capture order."""
    pictures = sorted(
        (
            picture
            for picture in ALL_PICTURES
            if first_day <= picture.day <= last_day
            and picture.place is not None
            and (not immich.real or picture.asset_id in immich.asset_ids)
        ),
        key=lambda picture: picture.taken_at,
    )
    places = []
    with httpx.Client(
        base_url=f"{immich.base_url}/api", headers={"x-api-key": immich.api_key}, timeout=60
    ) as client:
        for picture in pictures:
            response = client.get(f"/assets/{immich.id_of(picture.asset_id)}")
            response.raise_for_status()
            exif = response.json().get("exifInfo") or {}
            places.append((exif.get("city") or "", exif.get("country") or ""))
    return places


def most_held_town(immich: LibraryServer, first_day: str, last_day: str) -> tuple[str, str]:
    """The (town, country) holding most of these days' located pictures."""
    places = [place for place in stored_places(immich, first_day, last_day) if place[0]]
    assert places, f"no town stored for {first_day}..{last_day}"
    return Counter(places).most_common(1)[0][0]
