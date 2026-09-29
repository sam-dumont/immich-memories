"""Letters printed in the photos, read through Immich's OCR search."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from immich_memories.api.models import MetadataSearchResult
from immich_memories.api.search_service import SearchService
from immich_memories.free_text.printed import ImmichPrintedText

TAKEN = datetime(2024, 5, 1, tzinfo=UTC).isoformat()


def _page(ids: list[str], next_page: str | None) -> MetadataSearchResult:
    items = [
        {
            "id": i,
            "type": "IMAGE",
            "fileCreatedAt": TAKEN,
            "fileModifiedAt": TAKEN,
            "updatedAt": TAKEN,
        }
        for i in ids
    ]
    return MetadataSearchResult(assets={"items": items, "nextPage": next_page})


class _Immich:
    """WHY: replaces Immich's /search/metadata endpoint with two pages of OCR hits."""

    def __init__(self) -> None:
        self.asked: list[dict[str, Any]] = []
        self._pages = {1: _page(["a", "b"], "2"), 2: _page(["c"], None)}

    def search_metadata(self, **options: Any) -> MetadataSearchResult:
        self.asked.append(options)
        return self._pages[options["page"]]


def test_the_pictures_whose_printed_text_holds_the_word_across_every_page() -> None:
    immich = _Immich()

    found = ImmichPrintedText(immich).pictures_reading("velo club")

    assert found == frozenset({"a", "b", "c"})
    assert [asked["ocr"] for asked in immich.asked] == ["velo club", "velo club"]


@pytest.mark.asyncio
async def test_the_search_sends_the_text_to_immichs_ocr_filter() -> None:
    sent: list[dict[str, Any]] = []

    async def request(method: str, path: str, **options: Any) -> dict[str, Any]:
        sent.append(options["json"])
        return {"assets": {"items": [], "nextPage": None}}

    # WHY: replaces the HTTP call to Immich; the payload is what is under test.
    await SearchService(request).search_metadata(ocr="velo club", size=1000)

    assert sent[0]["ocr"] == "velo club"
