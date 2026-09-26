"""Pictures for the web client, from the shared cache or, once, from Immich."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Response
from fastapi.responses import StreamingResponse

from immich_memories.cache.thumbnail_cache import ThumbnailCache
from immich_memories.cache.thumbnail_sizes import load_thumbnail
from immich_memories.web.dependencies import (
    PlaybackOpener,
    PreviewFetcher,
    immich_playback,
    immich_preview,
    thumbnail_cache,
)

router = APIRouter(prefix="/api/v1/assets", tags=["media"])

_ASSET_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_CACHE_CONTROL = "private, max-age=86400"


@router.get("/{asset_id}/thumbnail", response_class=Response)
def thumbnail(
    asset_id: str,
    cache: Annotated[ThumbnailCache, Depends(thumbnail_cache)],
    fetch: Annotated[PreviewFetcher, Depends(immich_preview)],
    size: Literal["thumbnail", "preview"] = "thumbnail",
) -> Response:
    """The picture at grid or preview size; a miss is fetched from Immich and kept."""
    if not _ASSET_ID.match(asset_id):
        return Response(status_code=404)
    data = load_thumbnail(cache, asset_id, size)
    if data is None and (preview := fetch(asset_id)):
        cache.put(asset_id, "preview", preview)
        data = load_thumbnail(cache, asset_id, size)
    if data is None:
        return Response(status_code=404)
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": _CACHE_CONTROL})


@router.get("/{asset_id}/video", response_class=StreamingResponse)
def video(
    asset_id: str,
    open_playback: Annotated[PlaybackOpener, Depends(immich_playback)],
    range_header: Annotated[str | None, Header(alias="range")] = None,
) -> Response:
    """The playback rendition, streamed by byte range so the preview can seek to the cut's interval."""
    if not _ASSET_ID.match(asset_id):
        return Response(status_code=404)
    playback = open_playback(asset_id, range_header)
    if playback is None:
        return Response(status_code=404)
    headers = playback.headers | {"accept-ranges": "bytes", "cache-control": _CACHE_CONTROL}
    media_type = headers.pop("content-type", "video/mp4")
    return StreamingResponse(
        playback.chunks, status_code=playback.status, headers=headers, media_type=media_type
    )
