"""Grid-size thumbnails derived from Immich previews, shared by every page that serves them."""

from __future__ import annotations

import io
from collections.abc import Callable

from immich_memories.cache.thumbnail_cache import ThumbnailCache

# Grid cells are 140 px to 320 px wide; a 320 px long side covers a 2x display.
GRID_THUMBNAIL_PX = 320
# The People page draws a 64 px avatar; 128 px covers a 2x display.
AVATAR_PX = 128


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


def load_person_thumbnail(
    cache: ThumbnailCache, person_id: str, fetch: Callable[[str], bytes | None]
) -> bytes | None:
    """The face crop at avatar size, fetched from Immich once and cached after.

    Face crops live in the same session cache as the pictures, under their own
    key, so clearing the thumbnail cache forgets them too and nothing is kept
    that the pictures' own retention would not keep.
    """
    key = f"person-{person_id}"
    cached = cache.get(key, "thumbnail")
    if cached:
        return cached
    raw = fetch(person_id)
    if not raw:
        return None
    small = downscale_to_thumbnail(raw, px=AVATAR_PX)
    if small:
        cache.put(key, "thumbnail", small)
    return small
