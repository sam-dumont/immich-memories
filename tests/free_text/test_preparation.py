"""`--ask` prepares the window it needs (#2045): the pure pieces, not the full pipeline.

The CLI-level behavior -- the warning, the actual preparation, the answer -- is covered
end to end in `tests/free_text/test_generate_ask.py`. This is the arithmetic and date logic
those calls lean on.
"""

from __future__ import annotations

import time
from datetime import date
from types import SimpleNamespace

import pytest

from immich_memories.api.access_clients import AccessBoundClient
from immich_memories.config_loader import Config
from immich_memories.config_models import ImmichConfig
from immich_memories.db import open_store
from immich_memories.free_text import preparation as prep
from immich_memories.free_text.linking import WhenLink
from immich_memories.free_text.preparation import (
    DEFAULT_SECONDS_PER_PICTURE,
    Readiness,
    assess,
    estimate_seconds_per_picture,
    warning_line,
    window_of,
)
from immich_memories.timeperiod import custom_range
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


def test_the_rate_sums_only_preparation_spans_never_the_whole_run(monkeypatch) -> None:
    """#2045 (Opus review E): the bank's run also carries a root `run` span and a
    `discovery` span; summing those too would charge every picture for work that was
    never per-picture."""
    store = open_store()
    tracker = RunTracker(store=store, capture_system=False)
    tracker.start_run(source="prepare")
    with timing.collecting() as collected, timing.span("run"):
        with timing.span("discovery"):
            time.sleep(0.01)
        with timing.span("preparation.captions", items=100):
            time.sleep(0.01)
    SpanStore(store).save(tracker.run_id, collected)
    tracker.complete_run()

    rate = estimate_seconds_per_picture(store)

    measured = next(
        span.duration for span in collected.spans if span.name == "preparation.captions"
    )
    assert rate == measured / 100


def test_live_progress_is_reported_between_the_warning_and_the_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#2045 (Opus review G): preparation's own progress reaches the watcher as it runs,
    not just the warning's 0.0 and the finish's 1.0."""
    window = custom_range(date(2020, 1, 1), date(2020, 1, 2))
    monkeypatch.setattr(
        prep, "assess", lambda *_a, **_k: Readiness(window=window, missing=(object(), object()))
    )
    monkeypatch.setattr(prep, "estimate_seconds_per_picture", lambda _store: 1.0)
    monkeypatch.setattr(prep, "read_library", lambda _store, _editorial: "refreshed view")

    def fake_run(client, config, assets, *, progress=None):
        progress("captions", 1, 2)
        return SimpleNamespace(costs=lambda: ()), SimpleNamespace(complete=True)

    monkeypatch.setattr(prep, "run_preparation", fake_run)
    reports: list[tuple[str, float | None, float | None]] = []

    view, notice = prep.prepare_for_request(
        object(),
        SimpleNamespace(editorial=None),
        object(),
        "stale view",
        WhenLink(),
        today=date(2020, 1, 1),
        print_line=lambda _line: None,
        report=lambda message, fraction, remaining: reports.append((message, fraction, remaining)),
    )

    assert view == "refreshed view"
    assert notice is not None and notice.pictures == 2
    fractions = [fraction for _message, fraction, _remaining in reports]
    assert fractions[0] == 0.0  # the warning
    assert 0.0 < fractions[1] < 1.0  # live, between the warning and the completion
    assert fractions[-1] == 1.0  # the completion line


def test_a_household_window_check_discovers_every_named_accounts_pictures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#2044: a plain client/window search only ever sees the primary; naming a household's
    accounts has to read each one's own library (`HouseholdWindows`), or a partner's
    unprepared pictures would never be found, let alone prepared."""
    from tests.household_fake import PARTNER_KEY, PRIMARY_KEY, FakeHousehold, immich_config, picture

    FakeHousehold(
        library={
            PRIMARY_KEY: [picture("p-cat", "primary", 1, ())],
            PARTNER_KEY: [picture("q-cat", "partner", 2, ())],
        }
    ).install(monkeypatch)
    store = open_store()
    config = Config()
    config.immich = ImmichConfig(**immich_config())
    when = WhenLink(start=date(2025, 6, 1), end=date(2025, 6, 30))

    with AccessBoundClient(config.immich) as client:
        readiness = assess(
            client, config, store, when, today=date(2025, 6, 30), accounts=("primary", "partner")
        )

    assert {prep._asset_id(asset) for asset in readiness.missing} == {"p-cat", "q-cat"}


def test_a_one_account_window_check_never_asks_for_a_household(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No `accounts` is the plain, one-account read every window check has always done."""
    from tests.household_fake import PARTNER_KEY, PRIMARY_KEY, FakeHousehold, immich_config, picture

    FakeHousehold(
        library={
            PRIMARY_KEY: [picture("p-cat", "primary", 1, ())],
            PARTNER_KEY: [picture("q-cat", "partner", 2, ())],
        }
    ).install(monkeypatch)
    store = open_store()
    config = Config()
    config.immich = ImmichConfig(**immich_config())
    when = WhenLink(start=date(2025, 6, 1), end=date(2025, 6, 30))

    with AccessBoundClient(config.immich) as client:
        readiness = assess(client, config, store, when, today=date(2025, 6, 30))

    assert {prep._asset_id(asset) for asset in readiness.missing} == {"p-cat"}
