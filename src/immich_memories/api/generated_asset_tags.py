"""Durable provenance for completed films uploaded back into the source library."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

GENERATED_MEMORY_TAG = "immich-memories/generated"
_DETAIL_CONCURRENCY = 8


async def generated_asset_ids(
    request: Callable[..., Any], *, can_read_tags: bool = True
) -> frozenset[str]:
    """Completed films under the provenance tag, without requiring global tag access.

    Minimum read keys inspect video details through asset.read. Broader keys can
    use the tag index; neither path writes a tag or treats an unreadable library as empty.
    """
    if not can_read_tags:
        return await _generated_films_from_assets(request)
    tags = await request("GET", "/tags")
    matches = (
        [tag for tag in tags if isinstance(tag, dict) and tag.get("value") == GENERATED_MEMORY_TAG]
        if isinstance(tags, list)
        else []
    )
    if not matches or not isinstance(matches[0].get("id"), str):
        return frozenset()
    found: set[str] = set()
    page: int | None = 1
    while page:
        result = await request(
            "POST",
            "/search/metadata",
            json={"tagIds": [matches[0]["id"]], "size": 250, "page": page},
        )
        assets = (result or {}).get("assets", {})
        found.update(
            row["id"] for row in assets.get("items", ()) if isinstance(row, dict) and row.get("id")
        )
        page = assets.get("nextPage")
    return frozenset(found)


async def _generated_films_from_assets(request: Callable[..., Any]) -> frozenset[str]:
    found = set()
    page: int | str | None = 1
    while page:
        result = await request(
            "POST", "/search/metadata", json={"type": "VIDEO", "size": 250, "page": page}
        )
        assets = (result or {}).get("assets", {})
        rows = [row for row in assets.get("items", ()) if isinstance(row, dict) and row.get("id")]
        for start in range(0, len(rows), _DETAIL_CONCURRENCY):
            batch = rows[start : start + _DETAIL_CONCURRENCY]
            details = await asyncio.gather(
                *(_asset_detail(request, row) for row in batch), return_exceptions=True
            )
            for row, detail in zip(batch, details, strict=True):
                if isinstance(detail, BaseException):
                    raise detail
                if any(tag.get("value") == GENERATED_MEMORY_TAG for tag in detail.get("tags", ())):
                    found.add(row["id"])
        page = assets.get("nextPage")
    return frozenset(found)


async def _asset_detail(request: Callable[..., Any], row: dict) -> dict:
    if isinstance(row.get("tags"), list):
        return row
    return await request("GET", f"/assets/{row['id']}")
