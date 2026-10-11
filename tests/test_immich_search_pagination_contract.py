"""Every public metadata pager sends numeric JSON pages to Immich."""

import inspect
import json
from datetime import UTC, datetime

import httpx
import pytest

from immich_memories.api.immich import ImmichClient
from immich_memories.api.models import AssetType
from immich_memories.timeperiod import DateRange
from tests.immich_fakes import ImmichWire

SUBJECT = "6a1f0c3e-58d2-4b7a-9e41-0c2d7f8b3a15"
COMPANION = "b93d27e4-1f6a-4c08-8d5e-7a4c1e9f2b60"
ALBUM = "2c7e9b14-a3d5-4f86-b012-5e8d3c6a9f47"
OWNER = "e5b81d3a-7c29-4e60-a4f1-93d0b6c2e8a7"

WINDOW = DateRange(datetime(2030, 4, 1, tzinfo=UTC), datetime(2030, 4, 30, tzinfo=UTC))

CASES = [
    ("get_videos_for_date_range", {"date_range": WINDOW}),
    ("get_videos_for_person_and_date_range", {"person_id": SUBJECT, "date_range": WINDOW}),
    ("get_videos_for_all_persons", {"person_ids": [SUBJECT, COMPANION], "date_range": WINDOW}),
    ("get_photos_for_date_range", {"date_range": WINDOW}),
    ("get_photos_for_date_range", {"person_id": SUBJECT, "date_range": WINDOW}),
    ("get_photos_for_date_range", {"person_ids": [SUBJECT, COMPANION], "date_range": WINDOW}),
    ("get_live_photos_for_date_range", {"date_range": WINDOW}),
    ("get_live_photos_for_date_range", {"person_id": SUBJECT, "date_range": WINDOW}),
    (
        "get_live_photos_for_date_range",
        {"person_ids": [SUBJECT, COMPANION], "date_range": WINDOW},
    ),
    ("get_assets_for_date_range", {"date_range": WINDOW}),
    ("get_assets_for_person_and_date_range", {"person_id": SUBJECT, "date_range": WINDOW}),
    ("get_assets_for_any_person", {"person_ids": [SUBJECT, COMPANION], "date_range": WINDOW}),
    ("get_assets_for_album", {"album_id": ALBUM, "asset_type": AssetType.VIDEO}),
    ("get_assets_for_album", {"album_id": ALBUM, "asset_type": AssetType.IMAGE}),
    ("count_assets_with_people", {"person_ids": [SUBJECT], "owner_id": OWNER}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("version", ["v2", "v3"])
@pytest.mark.parametrize(("method", "kwargs"), CASES)
async def test_metadata_pagers_follow_string_continuations_with_numeric_requests(
    version, method, kwargs
):
    requests = []

    def serve(request):
        assert request.method == "POST" and request.url.path == "/api/search/metadata"
        payload = json.loads(request.content)
        requests.append(payload)
        page = payload["page"]
        assert 1 <= page <= 3
        asset = {
            "id": f"asset-{page}",
            "ownerId": OWNER,
            "type": payload.get("type", "IMAGE"),
            "fileCreatedAt": "2030-04-01T00:00:00Z",
            "fileModifiedAt": "2030-04-01T00:00:00Z",
            "updatedAt": "2030-04-01T00:00:00Z",
            "livePhotoVideoId": f"motion-{page}",
        }
        return httpx.Response(
            200,
            json={
                "assets": {
                    # An empty intermediate page must not discard the continuation.
                    "items": [] if page == 2 else [asset],
                    "nextPage": str(page + 1) if page < 3 else None,
                }
            },
        )

    # WHY: the Immich HTTP boundary; the wire refuses a page, size or id Immich would refuse.
    wire = ImmichWire(serve)
    client = ImmichClient("https://immich.test", "synthetic-key", api_version=version)
    client._client = httpx.AsyncClient(base_url="https://immich.test", transport=wire.transport)
    async with client:
        reader = client.search if method == "count_assets_with_people" else client
        pending = getattr(reader, method)(**kwargs)
        result = (
            [asset async for asset in pending] if inspect.isasyncgen(pending) else await pending
        )
    if method == "count_assets_with_people":
        assert result == 2
    else:
        assert {asset.id for asset in result} == {"asset-1", "asset-3"}
    wire.assert_clean()
    traversals = len(kwargs.get("person_ids", [])) or 1
    assert [body["page"] for body in requests] == [1, 2, 3] * traversals
