"""`--ask` prepares the window it needs (#2045): the pure pieces, not the full pipeline.

The CLI-level behavior -- the warning, the actual preparation, the answer -- is covered
end to end in `tests/free_text/test_generate_ask.py`. This is the arithmetic and date logic
those calls lean on.
"""

from __future__ import annotations

import time
from datetime import date

from immich_memories.db import open_store
from immich_memories.free_text.linking import WhenLink
from immich_memories.free_text.preparation import (
    DEFAULT_SECONDS_PER_PICTURE,
    estimate_seconds_per_picture,
    warning_line,
    window_of,
)
from immich_memories.tracking import timing
from immich_memories.tracking.run_tracker import RunTracker
from immich_memories.tracking.span_store import SpanStore

TODAY = date(2026, 10, 4)


class _NoYears:
    """WHY: stands in for the Immich client; this household's library has no assets yet."""

    def get_available_years(self, person_id: str | None = None) -> list[int]:
        return []


class _SomeYears:
    """WHY: stands in for the Immich client, answering only the years it was asked for."""

    def __init__(self, years: list[int]) -> None:
        self._years = years

    def get_available_years(self, person_id: str | None = None) -> list[int]:
        return self._years


def test_a_request_with_both_dates_is_checked_over_exactly_those_dates() -> None:
    when = WhenLink(start=date(2020, 1, 1), end=date(2020, 12, 31))

    window = window_of(when, _NoYears(), today=TODAY)

    assert (window.start.date(), window.end.date()) == (date(2020, 1, 1), date(2020, 12, 31))


def test_an_open_ended_request_runs_to_today() -> None:
    when = WhenLink(start=date(2020, 1, 1), end=None)

    window = window_of(when, _SomeYears([2018, 2019]), today=TODAY)

    assert (window.start.date(), window.end.date()) == (date(2020, 1, 1), TODAY)


def test_a_dateless_request_is_checked_over_the_whole_library() -> None:
    when = WhenLink(start=None, end=None)

    window = window_of(when, _SomeYears([2017, 2019, 2021]), today=TODAY)

    assert (window.start.date(), window.end.date()) == (date(2017, 1, 1), TODAY)


def test_a_dateless_request_on_an_empty_library_checks_only_today() -> None:
    when = WhenLink(start=None, end=None)

    window = window_of(when, _NoYears(), today=TODAY)

    assert (window.start.date(), window.end.date()) == (TODAY, TODAY)


def test_the_warning_names_the_count_and_an_estimate() -> None:
    line = warning_line([object(), object()], 120.0)

    assert (
        line
        == "2 pictures in this period aren't prepared yet; preparing them first takes about 2 min"
    )


def test_with_no_banked_rate_the_estimate_falls_back_to_the_documented_constant() -> None:
    store = open_store()

    assert estimate_seconds_per_picture(store) == DEFAULT_SECONDS_PER_PICTURE


def test_the_banks_own_past_timing_is_read_before_the_constant() -> None:
    store = open_store()
    tracker = RunTracker(store=store, capture_system=False)
    tracker.start_run(source="prepare")
    with timing.collecting() as collected, timing.span("preparation.captions", items=100):
        time.sleep(0.01)
    SpanStore(store).save(tracker.run_id, collected)
    tracker.complete_run()

    rate = estimate_seconds_per_picture(store)

    measured = next(
        span.duration for span in collected.spans if span.name == "preparation.captions"
    )
    assert rate == measured / 100
