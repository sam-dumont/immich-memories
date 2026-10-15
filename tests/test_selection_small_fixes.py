"""Small selection fixes before 1.0 (#2360): each test failed before its fix."""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import create_autospec

import pytest

from immich_memories.api.models import Asset, AssetType, ExifInfo


@pytest.mark.feature("selection.small-fixes")
def test_distinct_shots_keeps_an_undated_row_beside_dated_ones():
    """A naive `datetime.min` sorted among aware times raised TypeError."""
    from immich_memories.planning.distinct_shots import distinct_shots

    dated = {"asset_id": "a", "kind": "still", "taken": datetime(2024, 6, 1, 10, tzinfo=UTC)}
    later = {"asset_id": "b", "kind": "still", "taken": datetime(2024, 6, 1, 11, tzinfo=UTC)}
    undated = {"asset_id": "c", "kind": "still", "taken": None}

    kept = distinct_shots([later, undated, dated])

    assert [shot["asset_id"] for shot in kept] == ["c", "a", "b"]


@pytest.mark.parametrize(
    ("offered", "grant", "expected"),
    [
        ([0, 5, 5], 3, [0, 2, 1]),
        ([5, 0, 5], 3, [2, 0, 1]),
        ([0, 0, 2], 2, [0, 0, 2]),
        ([3, 3, 3], 4, [2, 1, 1]),
    ],
)
@pytest.mark.feature("selection.small-fixes")
def test_page_shares_never_grants_a_slot_to_a_page_with_nothing_to_offer(offered, grant, expected):
    from immich_memories.analysis.selection.pick_pages import page_shares

    shares = page_shares(offered, grant)

    assert shares == expected
    assert all(share <= count for share, count in zip(shares, offered, strict=True))


def _at(key: str, day: int, lat: float, lon: float) -> Asset:
    taken = datetime(2024, 8, day, 12, tzinfo=UTC)
    return Asset(
        id=key,
        type=AssetType.IMAGE,
        fileCreatedAt=taken,
        fileModifiedAt=taken,
        updatedAt=taken,
        exifInfo=ExifInfo(latitude=lat, longitude=lon),
    )


@pytest.mark.feature("selection.small-fixes")
def test_a_trip_on_the_equator_is_centred_on_every_one_of_its_pictures():
    """`if latitude` skipped 0.0, so the latitudes and longitudes averaged different pictures."""
    from immich_memories.analysis.sources.trip_discovery import discover_year_trips
    from immich_memories.api.sync_client import SyncImmichClient
    from immich_memories.config.models.automation import TripsConfig

    pictures = [_at("a", 10, 0.0, 10.0), _at("b", 11, 1.0, 11.0), _at("c", 12, 1.0, 12.0)]
    # WHY: the Immich read boundary; the autospec refuses any call the real client would.
    client = create_autospec(SyncImmichClient, instance=True)
    client.get_assets_for_date_range.return_value = pictures

    (trip,) = discover_year_trips(
        client, TripsConfig(homebase_latitude=45.0, homebase_longitude=5.0), 2024
    )

    assert trip.start_date == date(2024, 8, 10)
    assert (round(trip.centroid_lat, 4), round(trip.centroid_lon, 4)) == (0.6667, 11.0)
