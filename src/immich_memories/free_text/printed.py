"""The letters in the photos: Immich's OCR, read through its metadata search.

The store banks no OCR text; Immich reads it during its own jobs and filters on it with the
metadata search's `ocr` field. Forwarded pictures are searched too: a club's name on a jersey
arrives in the group chat's photos as often as in the owner's own.
"""

from __future__ import annotations

from typing import Any, Protocol

from immich_memories.api.models import MetadataSearchResult

_PAGE = 1000
# A word that half the library reads is no anchor; stop paging well before that.
_MOST_PAGES = 20


class _Search(Protocol):
    def search_metadata(self, **options: Any) -> MetadataSearchResult: ...


class ImmichPrintedText:
    """`PrintedText` against Immich: the ids of the pictures whose OCR text holds a word."""

    def __init__(self, immich: _Search) -> None:
        self._immich = immich

    def pictures_reading(self, text: str) -> frozenset[str]:
        """Every picture Immich's OCR search finds for `text`, page after page."""
        found: set[str] = set()
        page: int | None = 1
        while page is not None and page <= _MOST_PAGES:
            result = self._immich.search_metadata(ocr=text, page=page, size=_PAGE)
            found.update(asset.id for asset in result.all_assets)
            page = int(result.next_page) if result.next_page else None
        return frozenset(found)
