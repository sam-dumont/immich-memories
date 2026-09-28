"""Settings: every setting with its source, edited into the database, and the caches a run fills."""

from __future__ import annotations

import json
from itertools import groupby
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from immich_memories.config import get_config
from immich_memories.config_loader import Config
from immich_memories.config_sources import SettingSource, describe_settings
from immich_memories.settings_edit import SettingRefused, save_settings
from immich_memories.settings_store import secret_key_from_env
from immich_memories.web.dependencies import config_file, current_config
from immich_memories.web.schemas import SettingRow, SettingsForm, SettingsSection, SettingsView

router = APIRouter(prefix="/api/v1", tags=["settings"])

# The caches a run still fills. The Analysis table and the old players' preview folder are
# written by nothing now (#1508).
CacheName = Literal["video", "thumbnail"]


class CacheStats(BaseModel):
    name: CacheName
    items: int
    bytes: int


class Cleared(BaseModel):
    name: CacheName
    removed: int


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    return str(value)


def form_changes(entries: list[SettingSource], values: dict[str, Any]) -> dict[str, Any]:
    """The form values that differ from what the page showed, ready for `save_settings`.

    A blank secret keeps the stored one; lists and mappings are edited as JSON. A setting the
    environment or config.yaml sets is never saved. Raises `SettingRefused` when a JSON field
    does not parse.
    """
    changes: dict[str, Any] = {}
    for entry in entries:
        if entry.key not in values or not entry.editable:
            continue
        raw = values[entry.key]
        if entry.secret:
            if raw:
                changes[entry.key] = raw
            continue
        if raw in (entry.value, _as_text(entry.value)):
            continue
        if isinstance(entry.value, (list, dict)):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                raise SettingRefused(f"{entry.key}: not valid JSON") from None
        changes[entry.key] = raw
    return changes


def save_form(
    entries: list[SettingSource], values: dict[str, Any], *, path: Path | None = None
) -> str | None:
    """Save the edited values to the database; the refusal to show, or None when saved."""
    try:
        if changes := form_changes(entries, values):
            save_settings(changes, path=path)
    except SettingRefused as refusal:
        return str(refusal)
    return None


def _settings_view(path: Path) -> SettingsView:
    entries = describe_settings(get_config(reload=True), path=path)
    can_store = secret_key_from_env() is not None
    rows = [
        SettingRow(
            key=entry.key,
            value=entry.value,
            source=entry.source,
            override=entry.override,
            secret=entry.secret,
            unreadable=entry.unreadable,
            editable=entry.editable and (can_store or not entry.secret),
        )
        for entry in entries
    ]
    sections = [
        SettingsSection(name=name, settings=list(grouped))
        for name, grouped in groupby(rows, key=lambda row: row.key.split(".", 1)[0])
    ]
    return SettingsView(config_path=str(path), can_store_secrets=can_store, sections=sections)


@router.get("/settings", response_model=SettingsView)
def read_settings(path: Annotated[Path, Depends(config_file)]) -> SettingsView:
    """Every setting with its live value and its source, re-read from disk; secrets masked."""
    return _settings_view(path)


@router.post("/settings", response_model=SettingsView, responses={422: {}})
def save_settings_form(
    form: SettingsForm, path: Annotated[Path, Depends(config_file)]
) -> SettingsView:
    """Save the changed values to the database; config.yaml and the environment are never written.

    422 names the setting refused and why; nothing is saved then.
    """
    entries = describe_settings(get_config(reload=True), path=path)
    if refusal := save_form(entries, form.values, path=path):
        raise HTTPException(422, refusal)
    return _settings_view(path)


def _stats(config: Config) -> list[CacheStats]:
    from immich_memories.cache import ThumbnailCache, VideoDownloadCache

    video = VideoDownloadCache(cache_dir=config.cache.video_cache_path).get_stats()
    thumbnail = ThumbnailCache(
        cache_dir=config.cache.cache_path / "thumbnails",
        max_size_mb=config.cache.thumbnail_cache_max_size_mb,
    ).get_stats()
    return [
        CacheStats(
            name="video", items=video.get("file_count", 0), bytes=video.get("total_size_bytes", 0)
        ),
        CacheStats(
            name="thumbnail",
            items=thumbnail.get("file_count", 0),
            bytes=thumbnail.get("total_size_bytes", 0),
        ),
    ]


@router.get("/caches", response_model=list[CacheStats])
def caches(config: Annotated[Config, Depends(current_config)]) -> list[CacheStats]:
    """What each cache holds on disk."""
    return _stats(config)


@router.post("/caches/{name}/clear", response_model=Cleared)
def clear_cache(name: CacheName, config: Annotated[Config, Depends(current_config)]) -> Cleared:
    """Empty one cache; the next run fills it again as it needs."""
    from immich_memories.cache import ThumbnailCache, VideoDownloadCache

    if name == "video":
        removed = VideoDownloadCache(cache_dir=config.cache.video_cache_path).clear()
    else:
        removed = ThumbnailCache(
            cache_dir=config.cache.cache_path / "thumbnails",
            max_size_mb=config.cache.thumbnail_cache_max_size_mb,
        ).clear()
    return Cleared(name=name, removed=removed)
