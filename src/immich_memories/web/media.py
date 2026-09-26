"""Pictures for the web client, from the shared cache or, once, from Immich."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response

from immich_memories.cache.thumbnail_cache import ThumbnailCache
from immich_memories.cache.thumbnail_sizes import load_thumbnail
from immich_memories.web.dependencies import PreviewFetcher, immich_preview, thumbnail_cache

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
