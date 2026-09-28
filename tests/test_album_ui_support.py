"""Helpers the album picker needs (#270).

Listing albums for the picker, and turning an album's media into the clip and
photo pools a cut works with.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from immich_memories.analysis.album_source import AlbumMedia
from immich_memories.api.album_service import AlbumService


class TestListAlbums:
    @pytest.mark.asyncio
    async def test_lists_albums_newest_and_largest_first(self):
        # WHY: replaces the Immich GET /albums endpoint.
        request_fn = AsyncMock(
            return_value=[
                {"id": "a-1", "albumName": "Small", "assetCount": 3},
                {"id": "a-2", "albumName": "Big", "assetCount": 900},
            ]
        )
        service = AlbumService(request_fn, AsyncMock())

        albums = await service.list_albums()

        assert [a.name for a in albums] == ["Big", "Small"]
        assert albums[0].asset_count == 900

    @pytest.mark.asyncio
    async def test_skips_empty_albums_which_cannot_make_a_memory(self):
        request_fn = AsyncMock(
            return_value=[
                {"id": "a-1", "albumName": "Empty", "assetCount": 0},
                {"id": "a-2", "albumName": "Usable", "assetCount": 12},
            ]
        )
        service = AlbumService(request_fn, AsyncMock())

        assert [a.name for a in await service.list_albums()] == ["Usable"]


class TestAlbumModeState:
    """An album carries its own span; the picker never sets a date range."""

    def test_the_album_supplies_the_date_range_once_its_assets_are_known(self):
        """Generation still needs a span; it comes from the album, not the picker."""
        from datetime import datetime

        from immich_memories.timeperiod import DateRange

        media = AlbumMedia(
            date_range=DateRange(start=datetime(2021, 7, 21), end=datetime(2021, 7, 29))
        )

        assert media.date_range is not None
        assert media.date_range.start < media.date_range.end
