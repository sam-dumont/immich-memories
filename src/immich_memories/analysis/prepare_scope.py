"""Prepare a scope's annotations: the pipeline `prepare` and `--ask` share.

One definition of "prepare this window", so a caption-only free-text request pays the
same cost `prepare` would have, and never a cost of its own invention (#2045).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from immich_memories.analysis.preparation_report import ProducerClock
from immich_memories.timeperiod import DateRange
from immich_memories.tracking.timed import timed

if TYPE_CHECKING:
    from immich_memories.analysis.editorial_preparation import PreparationResult
    from immich_memories.config_loader import Config


@timed("discovery")
def eligible_source(client, config: Config, windows: list[DateRange]):
    """The corpus a cut over these windows would prepare, decided by the source pass itself."""
    from immich_memories.analysis.editorial_source import (
        fetch_full_window_source,
        library_source_scope,
    )
    from immich_memories.analysis.selection_source import (
        EditorialDependencies,
        EditorialSelectionRequest,
        prepare_editorial_source,
    )
    from immich_memories.tracking.report_context import record_assets

    scope = library_source_scope(client, config, windows)
    sources = fetch_full_window_source(client, scope)
    record_assets(sources)
    prepared = prepare_editorial_source(
        EditorialSelectionRequest(scope=scope),
        EditorialDependencies(source_fetcher=lambda _scope: sources),
    )
    return scope, sources, tuple(candidate.source for candidate in prepared.candidates)


def run_preparation(client, config: Config, assets) -> tuple[ProducerClock, PreparationResult]:
    """Run every configured producer over `assets`, charging the wall clock to each."""
    from immich_memories.analysis.editorial_preparation import prepare_editorial_annotations
    from immich_memories.analysis.subject_framing import face_boxes_of
    from immich_memories.cache.thumbnail_cache import ThumbnailCache
    from immich_memories.db import open_store
    from immich_memories.tracking.timing import active

    thumbnail_cache = ThumbnailCache(
        cache_dir=config.cache.cache_path / "thumbnails",
        max_size_mb=config.cache.thumbnail_cache_max_size_mb,
    )
    thumbnail_cache.begin_run()
    collected = active()
    clock = ProducerClock(spans=collected.spans if collected else None)
    result = prepare_editorial_annotations(
        assets=assets,
        store=open_store(config),
        thumbnail_cache=thumbnail_cache,
        preparation_config=config.editorial.preparation,
        triage_config=config.triage,
        head_versions=config.editorial.active_head_versions,
        inference_config=config.inference,
        llm_config=config.llm,
        description_model=config.editorial.description_model,
        pixel_producer_key=config.editorial.pixel_producer_key,
        fetch_preview=lambda asset_id: client.get_asset_thumbnail(asset_id, size="preview"),
        fetch_faces=lambda asset_id: face_boxes_of(client.get_asset_faces(asset_id)),
        read_playback=client.get_video_playback_range,
        progress=clock.report,
    )
    return clock, result
