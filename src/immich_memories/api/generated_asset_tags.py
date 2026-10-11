"""Durable provenance for completed films uploaded back into the source library."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from immich_memories.timeperiod import DateRange

GENERATED_MEMORY_TAG = "immich-memories/generated"
_DETAIL_CONCURRENCY = 8
# A window's bounds may be local wall time or UTC; a day either side covers every offset.
_WINDOW_MARGIN = timedelta(days=1)


async def generated_asset_ids(
    request: Callable[..., Any],
    *,
    can_read_tags: bool = True,
    within: Sequence[DateRange] | None = None,
) -> frozenset[str]:
    """Completed films under the provenance tag, without requiring global tag access.

    Minimum read keys inspect video details through asset.read, one request per video, so
    ``within`` bounds that walk to the videos taken inside a scope's own windows (#2353): a
    film elsewhere in the library is never a source of that scope anyway. Broader keys use
    the tag index; neither path writes a tag or treats an unreadable library as empty.
    """
    if not can_read_tags:
        return await _generated_films_from_assets(request, within)
    tags = await request("GET", "/tags")
    matches = (
        [tag for tag in tags if isinstance(tag, dict) and tag.get("value") == GENERATED_MEMORY_TAG]
        if isinstance(tags, list)
        else []
    )
    if not matches or not isinstance(matches[0].get("id"), str):
        return frozenset()
    found: set[str] = set()
    page = 1
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
        page = int(assets.get("nextPage") or 0)
    return frozenset(found)


async def _generated_films_from_assets(
    request: Callable[..., Any], within: Sequence[DateRange] | None
) -> frozenset[str]:
    rows: dict[str, dict] = {}
    for bounds in _taken_bounds(within):
        page = 1
        while page:
            query = {"type": "VIDEO", "size": 250, "page": page} | bounds
            assets = ((await request("POST", "/search/metadata", json=query)) or {}).get(
                "assets", {}
            )
            rows.update(
                (row["id"], row)
                for row in assets.get("items", ())
                if isinstance(row, dict) and row.get("id")
            )
            page = int(assets.get("nextPage") or 0)
    found = set()
    ordered = list(rows.values())
    for start in range(0, len(ordered), _DETAIL_CONCURRENCY):
        batch = ordered[start : start + _DETAIL_CONCURRENCY]
        details = await asyncio.gather(
            *(_asset_detail(request, row) for row in batch), return_exceptions=True
        )
        for row, detail in zip(batch, details, strict=True):
            if isinstance(detail, BaseException):
                raise detail
            if any(tag.get("value") == GENERATED_MEMORY_TAG for tag in detail.get("tags", ())):
                found.add(row["id"])
    return frozenset(found)


def _taken_bounds(within: Sequence[DateRange] | None) -> list[dict[str, str]]:
    """One search filter per window, or one unfiltered search for the whole library."""
    if not within:
        return [{}]
    return [
        {
            "takenAfter": _utc(window.start - _WINDOW_MARGIN),
            "takenBefore": _utc(window.end + _WINDOW_MARGIN),
        }
        for window in within
    ]


def _utc(moment: datetime) -> str:
    aware = moment if moment.tzinfo else moment.replace(tzinfo=UTC)
    return aware.astimezone(UTC).isoformat()


async def _asset_detail(request: Callable[..., Any], row: dict) -> dict:
    if isinstance(row.get("tags"), list):
        return row
    return await request("GET", f"/assets/{row['id']}")
