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

import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date

import sqlalchemy as sa

from immich_memories.analysis.editorial_preparation import PreparationResult
from immich_memories.analysis.preparation_report import human_duration, rate_report
from immich_memories.analysis.prepare_scope import admit_source, eligible_source, run_preparation
from immich_memories.api.models import Asset, VideoClipInfo
from immich_memories.db.tables import pipeline_runs
from immich_memories.free_text.library import LibraryView, read_library
from immich_memories.free_text.linking import WhenLink
from immich_memories.progress_lines import StageLines
from immich_memories.store.asset_annotations import AssetAnnotationFactRepository
from immich_memories.timeperiod import DateRange, custom_range
from immich_memories.tracking.span_store import SpanStore

# Measured on an M5 Max with smolvlm2-500m (#2045): 0.2-0.4 s/picture, the default reader.
# Used only until the store has its own banked timing to read instead.
DEFAULT_SECONDS_PER_PICTURE = 0.3

# How many of the most recently completed runs' caption spans feed the median rate.
_RATE_HISTORY = 5

# The producer name the caption stage reports under (`editorial_preparation_captions.py`).
_CAPTION_SPAN = "preparation.captions"


class PreparationFailed(RuntimeError):
    """Preparation left pictures without what a cut needs: the window still isn't ready."""


class NeedsPreparationPreview(Exception):
    """A dry run found an unprepared window: no pool was read. `notice` is the warning
    the caller already printed; `why` is its message, for a handler that wants text only."""

    def __init__(self, notice: Notice) -> None:
        super().__init__(notice.message)
        self.notice = notice
        self.why = notice.message


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


def _household_source(client, config, accounts: Sequence[str], window: DateRange):
    """`eligible_source`'s household twin: each chosen account's own window, not just the
    primary's (#2044) -- `AccessBoundClient`'s plain search stays on the primary alone."""
    from immich_memories.analysis.editorial_source import library_source_scope
    from immich_memories.analysis.household_source import HouseholdWindows

    scope = library_source_scope(client, config, [window])
    windows = HouseholdWindows(client, accounts)
    sources = [
        *windows.get_photos_for_date_range(window),
        *windows.get_videos_for_date_range(window),
    ]
    return admit_source(config, scope, sources)


def assess(
    client, config, store, when: WhenLink, *, today: date, accounts: Sequence[str] = ()
) -> Readiness:
    """The request's window, and the pictures in it with no caption yet.

    `accounts`, in a household run, reads each chosen account's own library (#2044): a
    plain client/window search sees only the primary's.
    """
    window = window_of(when, client, today=today)
    if accounts:
        assets = _household_source(client, config, accounts, window)
    else:
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


def _recent_run_ids(store, *, limit: int) -> list[str]:
    """The most recently completed runs, whatever their source: `generate` records
    "manual", not "prepare", so a rate the bank can use has to read every run, not one
    source's alone."""
    with store.connect() as connection:
        rows = connection.execute(
            sa.select(pipeline_runs.c.run_id)
            .where(pipeline_runs.c.status == "completed")
            .order_by(pipeline_runs.c.completed_at.desc())
            .limit(limit)
        ).scalars()
        return list(rows)


def estimate_seconds_per_picture(store) -> float:
    """The caption rate the store's own history measured, else the default reader's.

    The median of the caption stage's own `seconds / items` across the most recent
    completed runs that captioned anything: a single run's rate can be skewed by a cold
    model load or a handful of retries, and the median survives that better than one
    run's total. Only pictures that actually needed a caption are counted -- an already
    captioned picture a run merely revisited reports no `preparation.captions` work.
    """
    rates = [
        span.duration / span.items
        for run_id in _recent_run_ids(store, limit=_RATE_HISTORY)
        for span in SpanStore(store).load(run_id).spans
        if span.name == _CAPTION_SPAN and span.items
    ]
    return statistics.median(rates) if rates else DEFAULT_SECONDS_PER_PICTURE


def warning_line(missing: Sequence[Asset | VideoClipInfo], seconds: float) -> str:
    """The upfront warning the owner's ruling requires: the count and an estimate."""
    return (
        f"{len(missing):,} pictures in this period aren't prepared yet; "
        f"preparing them first takes about {human_duration(seconds)}"
    )


def _refuse_unreachable_captions(config) -> None:
    """Fail clearly before preparing, rather than mid-batch, when the caption service is down."""
    from immich_memories.preflight import CheckStatus, check_caption_endpoint

    result = check_caption_endpoint(config)
    if result.status is CheckStatus.ERROR:
        raise PreparationFailed(f"{result.message}: {result.details}")


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
    accounts: Sequence[str] = (),
) -> tuple[LibraryView, Notice | None]:
    """Prepare the request's window if it needs it, and return the view to read it with.

    A fully prepared window returns `view` unchanged and no notice: no warning, no
    preparation, no second read of the store. A dry run raises `NeedsPreparationPreview`
    after the warning: it previews what preparing would cost, never commits to paying it,
    and the pool is not known either way yet (#2045) -- never "not possible". `before_preparing`
    runs only when preparation is actually about to happen (the preflight checks `prepare`
    itself runs, never on a dry run or an already-prepared window), followed by a check that
    the caption service itself answers, so a down service fails clearly before any picture is
    touched rather than mid-batch. `report` carries the warning and live progress to a watcher
    such as the web client (message, fraction, remaining seconds); the same progress also
    prints to the terminal, `report` or not. `PreparationFailed` is raised, never swallowed
    into a vague "not possible" later, when a producer could not finish. `accounts`, in a
    household run (#2044), discovers and prepares every chosen account's own pictures, not
    just the primary's; the caller is the one that re-scopes the returned view to them.
    """
    readiness = assess(client, config, store, when, today=today, accounts=accounts)
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
        raise NeedsPreparationPreview(notice)
    if before_preparing:
        before_preparing()
    _refuse_unreachable_captions(config)
    print_line(f"Preparing {len(readiness.missing):,} pictures over 1 window")
    # The watcher redraws one bar; the terminal line is a log line, kept to a few per stage.
    stage_lines = StageLines()

    def live(producer: str, done: int, total: int) -> None:
        if not total:
            return
        remaining = rate * max(total - done, 0)
        message = f"Preparing {producer}: {done:,}/{total:,} pictures"
        if stage_lines.keeps(producer, done, total):
            print_line(message)
        if report:
            report(message, done / total, remaining)

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
