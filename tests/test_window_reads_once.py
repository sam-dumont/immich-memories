"""A run reads each date window from Immich once (#2711).

Discovery reads the film's windows, then the editor reads the same windows again for their
context: the same request twice, over a library that cannot change in between. A run's
client remembers what each window held; a client that never asked to remember reads fresh.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx

from immich_memories.api.immich import SyncImmichClient
from immich_memories.timeperiod import DateRange
from tests.immich_fakes import ImmichWire

_TAKEN = "2025-07-04T10:00:00.000Z"
_WINDOW = DateRange(datetime(2025, 7, 1, tzinfo=UTC), datetime(2025, 7, 31, 23, 59, tzinfo=UTC))
_OTHER = DateRange(datetime(2025, 8, 1, tzinfo=UTC), datetime(2025, 8, 31, 23, 59, tzinfo=UTC))


def _library():
    searches: list[dict] = []

    def serve(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        searches.append(body)
        kind = body.get("type", "IMAGE")
        item = {
            "id": f"9a1c1f0e-0000-4000-8000-00000000000{1 if kind == 'VIDEO' else 2}",
            "type": kind,
            "fileCreatedAt": _TAKEN,
            "fileModifiedAt": _TAKEN,
            "updatedAt": _TAKEN,
            "originalFileName": "IMG_0001.JPG",
        }
        return httpx.Response(200, json={"assets": {"items": [item], "nextPage": None}})

    return serve, searches


def _client(wire: ImmichWire) -> SyncImmichClient:
    client = SyncImmichClient(base_url="https://immich.test", api_key="key", api_version="v2")
    # WHY: Immich's metadata search, refusing what the real server refuses.
    client._async_client._client = httpx.AsyncClient(
        base_url="https://immich.test", transport=wire.transport
    )
    return client


def test_a_run_s_client_reads_each_window_once():
    serve, searches = _library()
    wire = ImmichWire(serve)
    with _client(wire) as client:
        client.remember_windows()
        first = (
            client.get_videos_for_date_range(_WINDOW),
            client.get_photos_for_date_range(_WINDOW),
        )
        again = (
            client.get_videos_for_date_range(_WINDOW),
            client.get_photos_for_date_range(_WINDOW),
        )
        client.get_photos_for_date_range(_OTHER)
    wire.assert_clean()

    assert [[a.id for a in kind] for kind in again] == [[a.id for a in kind] for kind in first]
    assert len(searches) == 3


def test_a_client_that_never_asked_to_remember_reads_fresh_every_time():
    serve, searches = _library()
    wire = ImmichWire(serve)
    with _client(wire) as client:
        client.get_photos_for_date_range(_WINDOW)
        client.get_photos_for_date_range(_WINDOW)
    wire.assert_clean()

    assert len(searches) == 2


def test_a_remembered_window_hands_back_a_list_the_caller_may_change():
    serve, _searches = _library()
    with _client(ImmichWire(serve)) as client:
        client.remember_windows()
        client.get_photos_for_date_range(_WINDOW).clear()

        assert len(client.get_photos_for_date_range(_WINDOW)) == 1
