"""One unsafe upstream identifier cannot discard the rest of a search."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from immich_memories.api.search_service import SearchService
from tests.test_search_service_date_pagination import WINDOW, _record


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["id", "livePhotoVideoId", "face", "person-face"])
@pytest.mark.parametrize("only_bad_on_first_page", [False, True])
async def test_search_skips_unsafe_records_and_reads_the_next_page(
    field, only_bad_on_first_page, caplog
):
    bad = deepcopy(_record(0, "IMAGE", 3))
    unsafe = "../../private-rejected-value"
    if field == "face":
        bad["faces"] = [{"id": unsafe}]
    elif field == "person-face":
        bad["people"][0]["faces"] = [{"id": unsafe}]
    else:
        bad[field] = unsafe
    first = [bad] if only_bad_on_first_page else [bad, _record(1, "IMAGE", 3)]
    pages = []

    # WHY: the remote search response supplies a corrupt record followed by valid pages.
    async def request(method, path, *, json):
        assert (method, path) == ("POST", "/search/metadata")
        pages.append(json["page"])
        return {
            "assets": {
                "items": first if json["page"] == 1 else [_record(2, "IMAGE", 3)],
                "nextPage": "2" if json["page"] == 1 else None,
                "total": len(first) + 1,
            }
        }

    assets = await SearchService(request).get_photos_for_date_range(WINDOW)

    assert [asset.id for asset in assets] == (
        ["asset-2"] if only_bad_on_first_page else ["asset-1", "asset-2"]
    )
    assert pages == [1, 2]
    assert "Skipping an Immich search result" in caplog.text
    assert unsafe not in caplog.text
    assert bad["originalFileName"] not in caplog.text


@pytest.mark.asyncio
async def test_a_different_schema_error_still_fails_discovery():
    bad = _record(0, "IMAGE", 1)
    del bad["fileCreatedAt"]

    # WHY: a missing required field is an API contract error, not an unsafe identifier.
    async def request(*args, **kwargs):
        return {"assets": {"items": [bad]}}

    with pytest.raises(ValidationError):
        await SearchService(request).search_metadata()
