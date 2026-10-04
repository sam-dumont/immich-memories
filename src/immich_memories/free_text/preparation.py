"""`--ask` prepares the period it needs, instead of answering "not possible" (#2045).

A caption-only subject has no shortlist to fill on demand, so free text is the one
request that has to pay for its own window. Before the pool is built, this measures
caption coverage over the request's own dates (the whole library for "along the
years") and prepares whatever is missing, through the same pipeline `prepare` uses
(`analysis.prepare_scope`). The owner's ruling (2026-10-04): warn with the count and
an estimate first, then prepare with the usual progress lines, then answer -- never
a silent wait, and never "not possible" on a window nobody has read yet. A dry run
(the CLI's `--dry-run`, and the web preview that runs it) shows the same warning but
never prepares: it is a preview, not a commitment to pay the cost.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date

from immich_memories.analysis.editorial_preparation import PreparationResult
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


class PreparationFailed(RuntimeError):
    """Preparation left pictures without what a cut needs: the window still isn't ready."""


@dataclass(frozen=True)
class Readiness:
    """What a request's window still needs before it can be read."""

    window: DateRange
    missing: tuple[Asset | VideoClipInfo, ...]


@dataclass(frozen=True)
class Notice:
    """The count and the estimate shown before any picture is prepared."""

    pictures: int
    estimated_seconds: float
    message: str


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
    """The caption rate the store's own history measured, else a documented constant.

    Only `preparation.*` leaf spans count: the bank's run also carries a root `run` span
    and a `discovery` span, and summing those too would charge every picture for work
    that was never per-picture.
    """
    history = SpanStore(store).latest("prepare", prefix="preparation.")
    if history is None:
        return DEFAULT_SECONDS_PER_PICTURE
    spans = [span for span in history.spans if span.name.startswith("preparation.")]
    pictures = max((span.items or 0 for span in spans), default=0)
    if not pictures:
        return DEFAULT_SECONDS_PER_PICTURE
    seconds = sum(span.duration for span in spans)
    return seconds / pictures if seconds else DEFAULT_SECONDS_PER_PICTURE


def warning_line(missing: Sequence[Asset | VideoClipInfo], seconds: float) -> str:
    """The upfront warning the owner's ruling requires: the count and an estimate."""
    return (
        f"{len(missing):,} pictures in this period aren't prepared yet; "
        f"preparing them first takes about {human_duration(seconds)}"
    )


def _failure_detail(result: PreparationResult) -> str:
    required = {
        key: ids for key, ids in result.missing_by_producer.items() if not key.startswith("motion:")
    }
    parts = [f"{producer}: {len(ids)} pictures" for producer, ids in required.items()]
    parts += [f"{key}: {detail}" for key, detail in result.failures.items()]
    return "; ".join(parts) or "no detail given"


def prepare_for_request(  # noqa: PLR0913 - every argument is one external boundary or callback
    client,
    config,
    store,
    view: LibraryView,
    when: WhenLink,
    *,
    today: date,
    dry_run: bool = False,
    print_line: Callable[[str], None],
    report: Callable[[str, float | None, float | None], None] | None = None,
    before_preparing: Callable[[], None] | None = None,
) -> tuple[LibraryView, Notice | None]:
    """Prepare the request's window if it needs it, and return the view to read it with.

    A fully prepared window returns `view` unchanged and no notice: no warning, no
    preparation, no second read of the store. A dry run stops after the warning: it
    previews what preparing would cost, never commits to paying it. `before_preparing`
    runs only when preparation is actually about to happen (the preflight checks `prepare`
    itself runs, never on a dry run or an already-prepared window). `report` carries the
    warning and live progress to a watcher such as the web client (message, fraction,
    remaining seconds); `PreparationFailed` is raised, never swallowed into a vague
    "not possible" later, when a producer could not finish.
    """
    readiness = assess(client, config, store, when, today=today)
    if not readiness.missing:
        return view, None
    rate = estimate_seconds_per_picture(store)
    seconds = rate * len(readiness.missing)
    warning = warning_line(readiness.missing, seconds)
    print_line(warning)
    if report:
        report(warning, 0.0, seconds)
    notice = Notice(len(readiness.missing), seconds, warning)
    if dry_run:
        return view, notice
    if before_preparing:
        before_preparing()
    print_line(f"Preparing {len(readiness.missing):,} pictures over 1 window")

    def live(producer: str, done: int, total: int) -> None:
        if not report or not total:
            return
        remaining = rate * max(total - done, 0)
        report(f"Preparing {producer}: {done:,}/{total:,} pictures", done / total, remaining)

    clock, result = run_preparation(client, config, readiness.missing, progress=live)
    pictures = len(readiness.missing)
    for line in rate_report(clock.costs(), pictures=pictures, library_size=pictures):
        print_line(line)
    if not result.complete:
        raise PreparationFailed(
            f"{pictures:,} pictures could not be prepared -- {_failure_detail(result)}"
        )
    if report:
        report(f"{pictures:,} pictures prepared", 1.0, 0.0)
    return read_library(store, config.editorial), notice
