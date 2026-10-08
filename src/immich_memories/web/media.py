"""Pictures for the web client, from the shared cache or, once, from Immich."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Response
from fastapi.responses import StreamingResponse

from immich_memories.cache.thumbnail_cache import ThumbnailCache
from immich_memories.cache.thumbnail_sizes import load_person_thumbnail, load_thumbnail
from immich_memories.web.dependencies import (
    AssetScope,
    PersonScope,
    PlaybackOpener,
    PreviewFetcher,
    asset_scope,
    immich_face,
    immich_playback,
    immich_preview,
    person_scope,
    thumbnail_cache,
)

router = APIRouter(prefix="/api/v1", tags=["media"])

_ASSET_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_CACHE_CONTROL = "private, max-age=86400"


@router.get("/assets/{asset_id}/thumbnail", response_class=Response)
def thumbnail(
    asset_id: str,
    scope: Annotated[AssetScope, Depends(asset_scope)],
    cache: Annotated[ThumbnailCache, Depends(thumbnail_cache)],
    fetch: Annotated[PreviewFetcher, Depends(immich_preview)],
    size: Literal["thumbnail", "preview"] = "thumbnail",
) -> Response:
    """The picture at grid or preview size; a miss is fetched from Immich and kept.

    With multiple accounts, the scope check asks which account can still read the id.
    Cached bytes also belong to the configured account set: removing an account or
    rotating a key makes its old entries inaccessible, even if a fetch finishes late.
    """
    if not _ASSET_ID.match(asset_id):
        return Response(status_code=404)
    account = scope(asset_id)
    if account is None:
        return Response(status_code=404)
    data = load_thumbnail(cache, asset_id, size)
    if data is None and (preview := fetch(asset_id, account)):
        cache.put(asset_id, "preview", preview)
        data = load_thumbnail(cache, asset_id, size)
    if data is None:
        return Response(status_code=404)
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": _CACHE_CONTROL})


def _video_media_type(upstream: str | None) -> str:
    """A video type, never whatever Immich said: the streamed bytes are served on this
    app's own origin, so an upstream `text/html` must not turn them into a page here."""
    if upstream and upstream.split(";", 1)[0].strip().lower().startswith("video/"):
        return upstream
    return "video/mp4"


@router.get("/assets/{asset_id}/video", response_class=StreamingResponse)
def video(
    asset_id: str,
    scope: Annotated[AssetScope, Depends(asset_scope)],
    open_playback: Annotated[PlaybackOpener, Depends(immich_playback)],
    range_header: Annotated[str | None, Header(alias="range")] = None,
) -> Response:
    """The playback rendition, streamed by byte range so the preview can seek to the cut's interval."""
    if not _ASSET_ID.match(asset_id):
        return Response(status_code=404)
    account = scope(asset_id)
    if account is None:
        return Response(status_code=404)
    playback = open_playback(asset_id, account, range_header)
    if playback is None:
        return Response(status_code=404)
    headers = playback.headers | {"accept-ranges": "bytes", "cache-control": _CACHE_CONTROL}
    media_type = _video_media_type(headers.pop("content-type", None))
    return StreamingResponse(
        playback.chunks, status_code=playback.status, headers=headers, media_type=media_type
    )


@router.get("/people/{person_id}/face", response_class=Response)
def face(
    person_id: str,
    scope: Annotated[PersonScope, Depends(person_scope)],
    cache: Annotated[ThumbnailCache, Depends(thumbnail_cache)],
    fetch: Annotated[PreviewFetcher, Depends(immich_face)],
) -> Response:
    """A person's face crop at avatar size, fetched from Immich once and cached after."""
    if not _ASSET_ID.match(person_id):
        return Response(status_code=404)
    account = scope(person_id)
    if account is None:
        return Response(status_code=404)
    data = load_person_thumbnail(cache, person_id, lambda pid: fetch(pid, account))
    if data is None:
        return Response(status_code=404)
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": _CACHE_CONTROL})
