"""Request-scoped inputs, overridable in tests through FastAPI's dependency overrides."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends

from immich_memories.cache.thumbnail_cache import ThumbnailCache
from immich_memories.config import get_config
from immich_memories.config_loader import Config

PreviewFetcher = Callable[[str], bytes | None]


@dataclass(frozen=True)
class Playback:
    """Immich's answer to one playback request, passed through to the browser."""

    status: int
    headers: dict[str, str]
    chunks: Iterator[bytes]


PlaybackOpener = Callable[[str, str | None], Playback | None]

# What a <video> element needs to seek and size the stream; nothing else of Immich's leaks out.
_PASSED_HEADERS = ("content-type", "content-length", "content-range", "last-modified", "etag")


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


def immich_playback(config: Annotated[Config, Depends(current_config)]) -> PlaybackOpener:
    """Stream an asset's playback rendition from Immich, the browser's byte range forwarded."""

    def open_playback(asset_id: str, byte_range: str | None) -> Playback | None:
        import httpx

        if not config.immich.url or not config.immich.api_key:
            return None
        client = httpx.Client(base_url=config.immich.url.rstrip("/"), timeout=30.0)
        headers = {"x-api-key": config.immich.api_key} | (
            {"range": byte_range} if byte_range else {}
        )
        try:
            request = client.build_request(
                "GET", f"/api/assets/{asset_id}/video/playback", headers=headers
            )
            response = client.send(request, stream=True)
        except httpx.HTTPError:
            client.close()
            return None
        if response.status_code not in (200, 206):
            response.close()
            client.close()
            return None

        def chunks() -> Iterator[bytes]:
            try:
                yield from response.iter_bytes(64 * 1024)
            finally:
                response.close()
                client.close()

        kept = {
            name: response.headers[name] for name in _PASSED_HEADERS if name in response.headers
        }
        return Playback(status=response.status_code, headers=kept, chunks=chunks())

    return open_playback
