"""Every public metadata pager sends numeric JSON pages to Immich."""

import inspect
import json
from datetime import UTC, datetime

import httpx
import pytest

from immich_memories.api.immich import ImmichClient
from immich_memories.api.models import AssetType
from immich_memories.timeperiod import DateRange

WINDOW = DateRange(datetime(2030, 4, 1, tzinfo=UTC), datetime(2030, 4, 30, tzinfo=UTC))

CASES = [
    ("get_all_videos_for_year", {"year": 2030}),
    ("get_videos_for_person_and_year", {"person_id": "subject", "year": 2030}),
    ("get_videos_for_date_range", {"date_range": WINDOW}),
    ("get_videos_for_person_and_date_range", {"person_id": "subject", "date_range": WINDOW}),
    ("get_videos_for_all_persons", {"person_ids": ["subject", "companion"], "date_range": WINDOW}),
    ("get_photos_for_date_range", {"date_range": WINDOW}),
    ("get_photos_for_date_range", {"person_id": "subject", "date_range": WINDOW}),
    ("get_photos_for_date_range", {"person_ids": ["subject", "companion"], "date_range": WINDOW}),
    ("get_live_photos_for_date_range", {"date_range": WINDOW}),
    ("get_live_photos_for_date_range", {"person_id": "subject", "date_range": WINDOW}),
    (
        "get_live_photos_for_date_range",
        {"person_ids": ["subject", "companion"], "date_range": WINDOW},
    ),
    ("get_assets_for_date_range", {"date_range": WINDOW}),
    ("get_assets_for_person_and_date_range", {"person_id": "subject", "date_range": WINDOW}),
    ("get_assets_for_any_person", {"person_ids": ["subject", "companion"], "date_range": WINDOW}),
    ("get_assets_for_album", {"album_id": "album", "asset_type": AssetType.VIDEO}),
    ("get_assets_for_album", {"album_id": "album", "asset_type": AssetType.IMAGE}),
    ("iter_videos_for_date_range", {"date_range": WINDOW}),
    ("iter_person_videos", {"person_id": "subject", "year": 2030}),
    ("count_assets_with_people", {"person_ids": ["subject"], "owner_id": "owner"}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("version", ["v2", "v3"])
@pytest.mark.parametrize(("method", "kwargs"), CASES)
async def test_metadata_pagers_follow_string_continuations_with_numeric_requests(
    version, method, kwargs
):
    requests = []

    def serve(request):
        # WHY: the Immich HTTP boundary validates JSON types before returning synthetic pages.
        assert request.method == "POST" and request.url.path == "/api/search/metadata"
        payload = json.loads(request.content)
        requests.append(payload)
        if type(payload["page"]) is not int:
            return httpx.Response(400, json={"message": "Validation failed"})
        page = payload["page"]
        assert 1 <= page <= 3
        assert type(payload["size"]) is int and 1 <= payload["size"] <= 1000
        asset = {
            "id": f"asset-{page}",
            "ownerId": "owner",
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

    client = ImmichClient("https://immich.test", "synthetic-key", api_version=version)
    client._client = httpx.AsyncClient(
        base_url="https://immich.test", transport=httpx.MockTransport(serve)
    )
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
    traversals = len(kwargs.get("person_ids", [])) or 1
    assert [body["page"] for body in requests] == [1, 2, 3] * traversals
