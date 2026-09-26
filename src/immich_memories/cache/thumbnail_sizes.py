"""Grid-size thumbnails derived from Immich previews, shared by every page that serves them."""

from __future__ import annotations

import io

from immich_memories.cache.thumbnail_cache import ThumbnailCache

# Grid cells are 140 px to 320 px wide; a 320 px long side covers a 2x display.
GRID_THUMBNAIL_PX = 320


def downscale_to_thumbnail(payload: bytes, *, px: int = GRID_THUMBNAIL_PX) -> bytes | None:
    """A cached preview re-encoded to grid size, or None if it does not decode."""
    from PIL import Image

    try:
        with Image.open(io.BytesIO(payload)) as opened:
            image = opened.convert("RGB")
            image.thumbnail((px, px))
            buffer = io.BytesIO()
            image.save(buffer, "JPEG", quality=80)
    except Exception:  # WHY: a corrupt preview must degrade to a placeholder, not a 500
        return None
    return buffer.getvalue()


def load_thumbnail(cache: ThumbnailCache, asset_id: str, size: str) -> bytes | None:
    """Bytes for the asset at the size, deriving the grid thumbnail from the preview once.

    The analysis pipeline fills the cache with previews, so the first request
    for a thumbnail pays one downscale and stores it; every later request is a
    file read.
    """
    if size == "preview":
        return cache.get(asset_id, "preview")
    cached = cache.get(asset_id, "thumbnail")
    if cached:
        return cached
    preview = cache.get(asset_id, "preview")
    if not preview:
        return None
    small = downscale_to_thumbnail(preview)
    if small:
        cache.put(asset_id, "thumbnail", small)
    return small
