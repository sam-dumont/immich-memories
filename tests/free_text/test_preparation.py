"""`--ask` prepares the window it needs (#2045): the pure pieces, not the full pipeline.

The CLI-level behavior -- the warning, the actual preparation, the answer -- is covered
end to end in `tests/free_text/test_generate_ask.py`. This is the arithmetic and date logic
those calls lean on.
"""

from __future__ import annotations

from datetime import date

import pytest

from immich_memories.api.access_clients import AccessBoundClient
from immich_memories.config_loader import Config
from immich_memories.config_models import ImmichConfig
from immich_memories.db import open_store
from immich_memories.free_text import preparation as prep
from immich_memories.free_text.library import LibraryView
from immich_memories.free_text.linking import WhenLink
from immich_memories.free_text.preparation import (
    DEFAULT_SECONDS_PER_PICTURE,
    assess,
    estimate_seconds_per_picture,
    warning_line,
    window_of,
)
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


def _banked_caption_span(store, *, source: str, duration: float, items: int) -> None:
    """A completed run whose bank holds exactly one caption span, of a stated rate."""
    from immich_memories.tracking.timing import Collector, Span

    tracker = RunTracker(store=store, capture_system=False)
    tracker.start_run(source=source)
    span = Span(1, "preparation.captions", None, 0.0, duration, items)
    SpanStore(store).save(tracker.run_id, Collector(spans=[span]))
    tracker.complete_run()


def test_the_rate_is_read_from_a_manual_run_not_only_a_prepare_one() -> None:
    """#2045 (Opus review E): `generate` records its run as "manual", not "prepare" -- a
    household that has only ever asked never has a "prepare"-sourced run to read."""
    store = open_store()
    _banked_caption_span(store, source="manual", duration=1.0, items=100)

    assert estimate_seconds_per_picture(store) == pytest.approx(0.01)


def test_the_rate_ignores_the_root_run_and_discovery_spans() -> None:
    """Only `preparation.captions` leaf spans count: a root `run` span and a `discovery`
    span would charge every picture for work that was never per-picture."""
    from immich_memories.tracking.timing import Collector, Span

    store = open_store()
    tracker = RunTracker(store=store, capture_system=False)
    tracker.start_run(source="manual")
    spans = [
        Span(1, "run", None, 0.0, 100.0, None),
        Span(2, "discovery", 1, 0.0, 50.0, None),
        Span(3, "preparation.captions", 1, 0.0, 1.0, 100),
    ]
    SpanStore(store).save(tracker.run_id, Collector(spans=spans))
    tracker.complete_run()

    assert estimate_seconds_per_picture(store) == pytest.approx(0.01)


def test_the_rate_is_the_median_of_several_recent_runs_whatever_their_source() -> None:
    """A realistic bank holds several runs, most of them `generate`'s own "manual" source;
    the median resists a single cold-load run skewing the estimate."""
    store = open_store()
    _banked_caption_span(store, source="manual", duration=1.0, items=10)  # 0.10 s/picture
    _banked_caption_span(store, source="manual", duration=4.0, items=10)  # 0.40 s/picture
    _banked_caption_span(store, source="prepare", duration=20.0, items=10)  # 2.00 s/picture

    assert estimate_seconds_per_picture(store) == pytest.approx(0.40)


def test_live_progress_reaches_the_watcher_through_the_public_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#2045 (Opus review G): preparation's own progress reaches the watcher as it runs,
    not just the warning's 0.0 and the finish's 1.0 -- exercised through the real
    `prepare_for_request` seam, mocking only the external boundaries it crosses."""
    from immich_memories.preflight import CheckResult, CheckStatus
    from tests.household_fake import PRIMARY_KEY, FakeHousehold, immich_config, picture

    # WHY: replaces the Immich HTTP API; the window check's own discovery stays real.
    FakeHousehold(
        library={
            PRIMARY_KEY: [
                picture("p-cat-1", "primary", 1, ()),
                picture("p-cat-2", "primary", 2, ()),
            ]
        }
    ).install(monkeypatch)
    # WHY: replaces reaching the real caption server over HTTP to check it answers.
    monkeypatch.setattr(
        "immich_memories.preflight.check_caption_endpoint",
        lambda _config: CheckResult("Captions", CheckStatus.OK, "ok"),
    )

    def fake_prepare(**kwargs):
        from immich_memories.analysis.editorial_preparation import PreparationResult

        total = len(kwargs["assets"])
        for done in range(1, total + 1):
            kwargs["progress"]("captions", done, total)
        return PreparationResult(requested=total, missing_by_producer={}, failures={})

    # WHY: replaces the real captioning model.
    monkeypatch.setattr(
        "immich_memories.analysis.editorial_preparation.prepare_editorial_annotations",
        fake_prepare,
    )
    store = open_store()
    config = Config()
    config.immich = ImmichConfig(**immich_config())
    reports: list[tuple[str, float | None, float | None]] = []
    when = WhenLink(start=date(2025, 6, 1), end=date(2025, 6, 30))
    stale = LibraryView(pictures=(), people={}, sharpness_line=None)

    with AccessBoundClient(config.immich) as client:
        prep.prepare_for_request(
            client,
            config,
            store,
            stale,
            when,
            today=date(2025, 6, 30),
            print_line=lambda _line: None,
            report=lambda message, fraction, remaining: reports.append(
                (message, fraction, remaining)
            ),
        )

    fractions = [fraction for _message, fraction, _remaining in reports]
    assert fractions[0] == 0.0  # the warning
    assert any(0.0 < fraction < 1.0 for fraction in fractions[1:-1])  # live
    assert fractions[-1] == 1.0  # the completion line


def test_an_unreachable_caption_service_fails_clearly_before_touching_a_picture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#2045 (Opus review H): a down caption service must fail with a clear message before
    any producer runs, not mid-batch."""
    from immich_memories.preflight import CheckResult, CheckStatus
    from tests.household_fake import PRIMARY_KEY, FakeHousehold, immich_config, picture

    # WHY: replaces the Immich HTTP API; the window check's own discovery stays real.
    FakeHousehold(library={PRIMARY_KEY: [picture("p-cat", "primary", 1, ())]}).install(monkeypatch)
    # WHY: replaces reaching the real caption server over HTTP, standing in for it being down.
    monkeypatch.setattr(
        "immich_memories.preflight.check_caption_endpoint",
        lambda _config: CheckResult(
            "Captions", CheckStatus.ERROR, "Caption server unreachable", "connection refused"
        ),
    )

    def _never(**_kwargs):
        raise AssertionError("the caption producer must never run once the service is down")

    # WHY: replaces the real captioning model; it must never be reached.
    monkeypatch.setattr(
        "immich_memories.analysis.editorial_preparation.prepare_editorial_annotations", _never
    )
    store = open_store()
    config = Config()
    config.immich = ImmichConfig(**immich_config())
    when = WhenLink(start=date(2025, 6, 1), end=date(2025, 6, 30))
    stale = LibraryView(pictures=(), people={}, sharpness_line=None)

    with AccessBoundClient(config.immich) as client, pytest.raises(prep.PreparationFailed) as error:
        prep.prepare_for_request(
            client, config, store, stale, when, today=date(2025, 6, 30), print_line=lambda _l: None
        )

    assert "Caption server unreachable" in str(error.value)


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
