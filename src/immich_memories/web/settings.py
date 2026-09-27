"""Settings: the configuration actually running, and the caches on disk."""

from __future__ import annotations

import shutil
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from immich_memories.config import get_config, get_config_path
from immich_memories.config_loader import Config
from immich_memories.security import redact_config
from immich_memories.web.dependencies import current_config

router = APIRouter(prefix="/api/v1", tags=["settings"])

CacheName = Literal["analysis", "video", "thumbnail", "preview"]


class ActiveConfig(BaseModel):
    path: str
    preset: str | None
    sections: dict[str, Any]


class CacheStats(BaseModel):
    name: CacheName
    items: int
    bytes: int


class Cleared(BaseModel):
    name: CacheName
    removed: int


@router.get("/config", response_model=ActiveConfig)
def active_config() -> ActiveConfig:
    """The configuration this server runs with, env overrides applied, secrets masked."""
    config = get_config(reload=True)
    return ActiveConfig(
        path=str(get_config_path()),
        preset=config.preset,
        sections=redact_config(config.model_dump(mode="json")),
    )


def _preview_dir(config: Config):
    return config.cache.cache_path / "preview-cache"


def _stats(config: Config) -> list[CacheStats]:
    from immich_memories.cache import ThumbnailCache, VideoAnalysisCache, VideoDownloadCache

    analysis = VideoAnalysisCache(db_path=config.cache.database_path).get_stats()
    video = VideoDownloadCache(cache_dir=config.cache.video_cache_path).get_stats()
    thumbnail = ThumbnailCache(
        cache_dir=config.cache.cache_path / "thumbnails",
        max_size_mb=config.cache.thumbnail_cache_max_size_mb,
    ).get_stats()
    previews = list(_preview_dir(config).glob("*.mp4")) if _preview_dir(config).is_dir() else []
    return [
        CacheStats(
            name="analysis", items=analysis["total_videos"], bytes=analysis["database_size_bytes"]
        ),
        CacheStats(
            name="video", items=video.get("file_count", 0), bytes=video.get("total_size_bytes", 0)
        ),
        CacheStats(
            name="thumbnail",
            items=thumbnail.get("file_count", 0),
            bytes=thumbnail.get("total_size_bytes", 0),
        ),
        CacheStats(
            name="preview", items=len(previews), bytes=sum(p.stat().st_size for p in previews)
        ),
    ]


@router.get("/caches", response_model=list[CacheStats])
def caches(config: Annotated[Config, Depends(current_config)]) -> list[CacheStats]:
    """What each cache holds on disk."""
    return _stats(config)


@router.post("/caches/{name}/clear", response_model=Cleared)
def clear_cache(name: CacheName, config: Annotated[Config, Depends(current_config)]) -> Cleared:
    """Empty one cache; the next run fills it again as it needs."""
    from immich_memories.cache import ThumbnailCache, VideoAnalysisCache, VideoDownloadCache

    if name == "analysis":
        removed = VideoAnalysisCache(db_path=config.cache.database_path).clear_all()
    elif name == "video":
        removed = VideoDownloadCache(cache_dir=config.cache.video_cache_path).clear()
    elif name == "thumbnail":
        removed = ThumbnailCache(
            cache_dir=config.cache.cache_path / "thumbnails",
            max_size_mb=config.cache.thumbnail_cache_max_size_mb,
        ).clear()
    else:
        previews = list(_preview_dir(config).glob("*.mp4")) if _preview_dir(config).is_dir() else []
        removed = len(previews)
        if _preview_dir(config).is_dir():
            shutil.rmtree(_preview_dir(config))
    return Cleared(name=name, removed=removed)
