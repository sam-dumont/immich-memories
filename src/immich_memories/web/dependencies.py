"""Request-scoped inputs, overridable in tests through FastAPI's dependency overrides."""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends

from immich_memories.cache.thumbnail_cache import ThumbnailCache
from immich_memories.config import get_config
from immich_memories.config_loader import Config

PreviewFetcher = Callable[[str], bytes | None]


def current_config() -> Config:
    return get_config()


@lru_cache(maxsize=4)
def _open_cache(directory: Path, max_size_mb: int) -> ThumbnailCache:
    return ThumbnailCache(cache_dir=directory, max_size_mb=max_size_mb)


def thumbnail_cache(config: Annotated[Config, Depends(current_config)]) -> ThumbnailCache:
    """One cache per server, not per browser session: every client reads the same files."""
    return _open_cache(
        config.cache.cache_path / "thumbnails", config.cache.thumbnail_cache_max_size_mb
    )


def immich_preview(config: Annotated[Config, Depends(current_config)]) -> PreviewFetcher:
    """Fetch an asset's preview from Immich server-side, so the API key never reaches a browser."""

    def fetch(asset_id: str) -> bytes | None:
        from immich_memories.api.sync_client import SyncImmichClient

        if not config.immich.url or not config.immich.api_key:
            return None
        try:
            with SyncImmichClient(
                base_url=config.immich.url, api_key=config.immich.api_key
            ) as client:
                return client.get_asset_thumbnail(asset_id, size="preview")
        except Exception:  # noqa: BLE001 - an unreachable picture is a placeholder, not a 500
            return None

    return fetch
