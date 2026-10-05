"""Prepare a scope's annotations: the pipeline `prepare` and `--ask` share.

One definition of "prepare this window", so a caption-only free-text request pays the
same cost `prepare` would have, and never a cost of its own invention (#2045).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from immich_memories.analysis.preparation_report import ProducerClock
from immich_memories.timeperiod import DateRange
from immich_memories.tracking.timed import timed

if TYPE_CHECKING:
    from immich_memories.analysis.editorial_preparation import PreparationResult
    from immich_memories.analysis.selection_source import SourceScope
    from immich_memories.api.models import Asset, VideoClipInfo
    from immich_memories.config_loader import Config


def admit_source(
    config: Config, scope: SourceScope, sources: Sequence[Asset | VideoClipInfo]
) -> tuple[Asset | VideoClipInfo, ...]:
    """`sources` passed through the same admission a cut and `prepare` both pay (dedup,
    camera EXIF, minimum resolution): the source-eligible corpus, whoever fetched it."""
    from immich_memories.analysis.selection_source import (
        EditorialDependencies,
        EditorialSelectionRequest,
        prepare_editorial_source,
    )
    from immich_memories.tracking.report_context import record_assets

    record_assets(sources)
    prepared = prepare_editorial_source(
        EditorialSelectionRequest(scope=scope),
        EditorialDependencies(source_fetcher=lambda _scope: sources),
    )
    return tuple(candidate.source for candidate in prepared.candidates)


@timed("discovery")
def eligible_source(client, config: Config, windows: list[DateRange]):
    """The corpus a cut over these windows would prepare, decided by the source pass itself."""
    from immich_memories.analysis.editorial_source import (
        fetch_full_window_source,
        library_source_scope,
    )

    scope = library_source_scope(client, config, windows)
    sources = fetch_full_window_source(client, scope)
    return scope, sources, admit_source(config, scope, sources)


def run_preparation(
    client,
    config: Config,
    assets,
    *,
    progress: Callable[[str, int, int], None] | None = None,
) -> tuple[ProducerClock, PreparationResult]:
    """Run every configured producer over `assets`, charging the wall clock to each.

    `progress`, when given, is told the same (producer, done, total) the wall clock
    charges, live, for a caller that wants its own running estimate (a CLI line, a web
    job's progress file) rather than the clock's after-the-fact report.
    """
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
    # Preview reads here only ever see an asset id, not the asset itself (#2114):
    # built once per batch, so an edited picture's preview still asks for its
    # edited render.
    edited_by_id = {asset.id: asset.is_edited for asset in assets}

    def report(producer: str, done: int, total: int) -> None:
        clock.report(producer, done, total)
        if progress:
            progress(producer, done, total)

    def fetch_preview(asset_id: str) -> bytes:
        return client.get_asset_thumbnail(
            asset_id, size="preview", edited=edited_by_id.get(asset_id, False)
        )

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
        fetch_preview=fetch_preview,
        fetch_faces=lambda asset_id: face_boxes_of(client.get_asset_faces(asset_id)),
        read_playback=client.get_video_playback_range,
        progress=report,
    )
    return clock, result


_PRODUCER_WORDS = {"description": "captions", "head": "model heads", "pixel": "pixel facts"}


@dataclass(frozen=True)
class Unprepared:
    """How many pictures of a period still owe a fact, and which producers owe them."""

    pictures: int
    of: int
    by_producer: dict[str, int]

    def line(self) -> str:
        if not self.pictures:
            return f"all {self.of:,} pictures in this period are prepared"
        owed = ", ".join(f"{words} {count:,}" for words, count in self.by_producer.items())
        return (
            f"{self.pictures:,} of {self.of:,} pictures in this period aren't prepared yet "
            f"({owed}); the run prepares the ones its cut reaches"
        )


def unprepared_pictures(config: Config, store, asset_ids: Sequence[str]) -> Unprepared:
    """What a run over these pictures would still have to prepare, read from the store only.

    Counts only the producers this tier asks for: a metadata-only NAS never owes a caption.
    Nothing is fetched and nothing is written, so a dry run can afford to ask.
    """
    from immich_memories.analysis.editorial_description_outcomes import cached_preview
    from immich_memories.store.editorial_preparation import missing_facts

    preparation = config.editorial.preparation
    cache_path = config.cache.cache_path / "thumbnails"
    missing, _unavailable = missing_facts(
        store,
        asset_ids,
        description_model=config.editorial.description_model,
        head_versions=config.editorial.active_head_versions if preparation.demands_models else {},
        pixel_producer_key=config.editorial.pixel_producer_key,
        preview_for=lambda asset_id: cached_preview(cache_path, asset_id),
    )
    owed: dict[str, set[str]] = {}
    for key, ids in missing.items():
        kind = key.split(":", 1)[0]
        if kind == "description" and not preparation.demands_captions:
            continue
        owed.setdefault(_PRODUCER_WORDS.get(kind, kind), set()).update(ids)
    pictures = set().union(*owed.values()) if owed else set()
    return Unprepared(
        pictures=len(pictures),
        of=len(set(asset_ids)),
        by_producer={words: len(ids) for words, ids in owed.items()},
    )
