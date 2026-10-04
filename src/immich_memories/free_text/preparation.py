"""`--ask` prepares the period it needs, instead of answering "not possible" (#2045).

A caption-only subject has no shortlist to fill on demand, so free text is the one
request that has to pay for its own window. Before the pool is built, this measures
caption coverage over the request's own dates (the whole library for "along the
years") and prepares whatever is missing, through the same pipeline `prepare` uses
(`analysis.prepare_scope`). The owner's ruling (2026-10-04): warn with the count and
an estimate first, then prepare with the usual progress lines, then answer -- never
a silent wait, and never "not possible" on a window nobody has read yet.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date

from immich_memories.analysis.preparation_report import human_duration, rate_report
from immich_memories.analysis.prepare_scope import eligible_source, run_preparation
from immich_memories.api.models import Asset, VideoClipInfo
from immich_memories.free_text.library import LibraryView, read_library
from immich_memories.free_text.linking import WhenLink
from immich_memories.store.asset_annotations import AssetAnnotationFactRepository
from immich_memories.timeperiod import DateRange, custom_range
from immich_memories.tracking.span_store import SpanStore

# Measured on an M5 Max with smolvlm2-500m (#2045): 0.2-0.4 s/picture. Used only until
# the store has its own banked timing to read instead.
DEFAULT_SECONDS_PER_PICTURE = 0.3


@dataclass(frozen=True)
class Readiness:
    """What a request's window still needs before it can be read."""

    window: DateRange
    missing: tuple[Asset | VideoClipInfo, ...]


def _asset_id(source: Asset | VideoClipInfo) -> str:
    return source.asset.id if isinstance(source, VideoClipInfo) else source.id


def window_of(when: WhenLink, client, *, today: date) -> DateRange:
    """The request's own dates, or the whole library's when it names none."""
    if when.start and when.end:
        return custom_range(when.start, when.end)
    years = client.get_available_years()
    earliest = date(min(years), 1, 1) if years else today
    return custom_range(when.start or earliest, when.end or today)


def assess(client, config, store, when: WhenLink, *, today: date) -> Readiness:
    """The request's window, and the pictures in it with no caption yet."""
    window = window_of(when, client, today=today)
    _scope, _sources, assets = eligible_source(client, config, [window])
    if not assets:
        return Readiness(window=window, missing=())
    ids = tuple(_asset_id(asset) for asset in assets)
    batch = AssetAnnotationFactRepository(
        store,
        description_model=config.editorial.description_model,
        head_versions=config.editorial.active_head_versions,
        pixel_producer_key=config.editorial.pixel_producer_key,
    ).facts_for(ids)
    captioned = {fact.asset_id for fact in batch.facts if fact.description}
    missing = tuple(asset for asset in assets if _asset_id(asset) not in captioned)
    return Readiness(window=window, missing=missing)


def estimate_seconds_per_picture(store) -> float:
    """The caption rate the store's own history measured, else a documented constant."""
    history = SpanStore(store).latest("prepare", prefix="preparation.")
    if history is None:
        return DEFAULT_SECONDS_PER_PICTURE
    pictures = max((span.items or 0 for span in history.spans), default=0)
    if not pictures:
        return DEFAULT_SECONDS_PER_PICTURE
    seconds = sum(span.duration for span in history.spans)
    return seconds / pictures if seconds else DEFAULT_SECONDS_PER_PICTURE


def warning_line(missing: Sequence[Asset | VideoClipInfo], seconds: float) -> str:
    """The upfront warning the owner's ruling requires: the count and an estimate."""
    return (
        f"{len(missing):,} pictures in this period aren't prepared yet; "
        f"preparing them first takes about {human_duration(seconds)}"
    )


def prepare_for_request(
    client,
    config,
    store,
    view: LibraryView,
    when: WhenLink,
    *,
    today: date,
    print_line: Callable[[str], None],
    report: Callable[[str, float | None, float | None], None] | None = None,
) -> LibraryView:
    """Prepare the request's window if it needs it, and return the view to read it with.

    A fully prepared window returns `view` unchanged: no warning, no preparation, no
    second read of the store. `report` carries the same warning and a completion line
    to a watcher such as the web client (message, fraction, remaining seconds).
    """
    readiness = assess(client, config, store, when, today=today)
    if not readiness.missing:
        return view
    seconds = estimate_seconds_per_picture(store) * len(readiness.missing)
    warning = warning_line(readiness.missing, seconds)
    print_line(warning)
    if report:
        report(warning, 0.0, seconds)
    print_line(f"Preparing {len(readiness.missing):,} pictures over 1 window")
    clock, result = run_preparation(client, config, readiness.missing)
    for line in rate_report(clock.costs(), pictures=len(readiness.missing), library_size=1000):
        print_line(line)
    if report:
        report(f"{len(readiness.missing):,} pictures prepared", 1.0, 0.0)
    if not result.complete:
        print_line("Some pictures could not be prepared; the answer reads what is")
    return read_library(store, config.editorial)
