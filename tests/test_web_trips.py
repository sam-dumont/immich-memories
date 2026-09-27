"""The trips a year holds, numbered the way `generate --trip-index` reads them."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from immich_memories.analysis.trip_detection import DetectedTrip
from immich_memories.web.library import trip_finder
from tests.web_api_fixtures import api_client, config_in


def _trip(place: str, start: date, end: date, count: int) -> DetectedTrip:
    return DetectedTrip(
        start_date=start,
        end_date=end,
        location_name=place,
        asset_count=count,
        centroid_lat=0.0,
        centroid_lon=0.0,
    )


def test_trips_keep_discovery_order_and_number_from_one(tmp_path: Path):
    asked: list[tuple[int, list[str]]] = []

    def find(year: int, people: list[str]) -> list[DetectedTrip]:
        asked.append((year, people))
        return [
            _trip("Lisbon", date(2024, 4, 2), date(2024, 4, 6), 120),
            _trip("Alps", date(2024, 2, 10), date(2024, 2, 10), 9),
        ]

    client = api_client(config_in(tmp_path))
    # WHY: discovery reads the whole year's GPS from Immich; the e2e runs it against the fake.
    client.app.dependency_overrides[trip_finder] = lambda: find

    trips = client.get("/api/v1/trips", params={"year": 2024, "person": ["Ana"]}).json()

    assert asked == [(2024, ["Ana"])]
    assert trips == [
        {
            "index": 1,
            "place": "Lisbon",
            "start": "2024-04-02",
            "end": "2024-04-06",
            "days": 5,
            "pictures": 120,
        },
        {
            "index": 2,
            "place": "Alps",
            "start": "2024-02-10",
            "end": "2024-02-10",
            "days": 1,
            "pictures": 9,
        },
    ]


def test_an_immich_refusal_is_a_bad_gateway_that_says_so(tmp_path: Path):
    from immich_memories.api.immich import ImmichAPIError
    from immich_memories.web.library import immich_client

    class Refusing:
        def list_albums(self):
            raise ImmichAPIError("Immich answered 500 for /albums")

    client = api_client(config_in(tmp_path))
    # WHY: the Immich server is the boundary; this one refuses every read.
    client.app.dependency_overrides[immich_client] = lambda: Refusing()

    answer = client.get("/api/v1/albums")

    assert answer.status_code == 502
    assert "Immich answered 500" in answer.json()["detail"]


def test_the_holidays_the_brief_offers_are_the_ones_the_pipeline_resolves(tmp_path: Path):
    from immich_memories.memory_types.factory import KNOWN_HOLIDAYS

    client = api_client(config_in(tmp_path))

    english = client.get("/api/v1/holidays").json()
    french = client.get("/api/v1/holidays", params={"lang": "fr"}).json()

    assert [h["key"] for h in english] == list(KNOWN_HOLIDAYS)
    christmas = {h["key"]: h["name"] for h in english}["christmas"]
    assert christmas == "Christmas"
    assert {h["key"]: h["name"] for h in french}["christmas"] == "Noël"
