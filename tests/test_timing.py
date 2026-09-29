"""Run timing keeps concurrent parentage and failed work, without touching a store."""

import logging

import pytest

from immich_memories.tracking import timing


def test_failed_span_keeps_parent_warning_and_elapsed_time():
    moments = iter([10.0, 11.0, 13.0, 15.0])
    with (
        timing.collecting(now=lambda: next(moments)) as collected,
        pytest.raises(ValueError, match="broken"),
        timing.span("selection"),
        timing.span("selection.reader", items=2),
    ):
        logging.getLogger("immich_memories.reader").warning("retry exhausted")
        raise ValueError("broken")

    child, parent = collected.spans
    assert child.parent_id == parent.span_id
    assert child.duration == 2.0
    assert child.items == 2
    assert child.error["type"] == "ValueError"
    assert child.warnings == ["retry exhausted"]
    assert parent.duration == 5.0
    assert timing.active() is None


def test_preparation_costs_read_the_measured_spans():
    from immich_memories.analysis.preparation_report import ProducerClock

    moments = iter([1.0, 5.0])
    with timing.collecting(now=lambda: next(moments)) as collected:
        clock = ProducerClock(spans=collected.spans)
        with timing.span("preparation.detectors", items=8):
            clock.report("detectors", 16, 16)
    (cost,) = clock.costs()
    assert cost.producer == "detectors"
    assert cost.pending == 16
    assert cost.seconds_per_picture(8) == 0.5


def test_secrets_are_removed_before_buffering_logs_and_failures():
    import secrets

    from immich_memories.logging_config import install_secret_redaction

    secret = secrets.token_urlsafe(24)
    install_secret_redaction([secret])
    with timing.collecting() as collected, pytest.raises(ValueError), timing.span("reader"):
        logging.getLogger("immich_memories.reader").warning("request failed: %s", secret)
        raise ValueError(f"request failed: {secret}")

    assert secret not in str(collected.logs)
    assert secret not in str(collected.spans[0].to_dict())


def test_concurrent_runs_keep_their_own_warnings_and_parentage():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    ready = Barrier(2)

    def run(name):
        with timing.collecting() as collected, timing.span(name):
            ready.wait(timeout=10)
            with timing.span("reader"):
                logging.getLogger("immich_memories.reader").warning(name)
        return collected

    with ThreadPoolExecutor(max_workers=2) as workers:
        left, right = list(workers.map(run, ("left", "right")))
    assert left.logs == ["left"]
    assert right.logs == ["right"]
    for collected in (left, right):
        child, parent = collected.spans
        assert child.parent_id == parent.span_id
        assert child.warnings == [parent.name]


@pytest.mark.parametrize(("code", "status"), [(0, "completed"), (None, "completed"), (2, "failed")])
def test_an_exit_ends_the_run_by_its_status_code(code, status):
    import sys

    from immich_memories.db import open_store
    from immich_memories.tracking.run_observations import observe_run

    with (
        pytest.raises(SystemExit),
        observe_run(open_store(), source="manual", capture_system=False) as tracker,
    ):
        sys.exit(code)
    saved = tracker.db.get_run(tracker.run_id)
    assert saved.status == status
    run_span = next(span for span in _spans(tracker) if span.name == "run")
    assert (run_span.error is None) == (status == "completed")


def _spans(tracker):
    from immich_memories.tracking.span_store import SpanStore

    return SpanStore(tracker.db.store).load(tracker.run_id).spans


def test_run_logs_keep_the_last_lines_and_count_every_level(monkeypatch):
    # WHY: a small cap stands in for the real one without logging thousands of lines.
    monkeypatch.setattr(timing, "LOG_LINES", 10)
    log = logging.getLogger("immich_memories.fixture")
    with timing.collecting() as collected:
        for number in range(25):
            log.warning("line %d", number)
        log.error("last")
    assert len(collected.logs) == 10
    assert collected.logs[-1].endswith("last")
    assert collected.diagnostics["log_counts"] == {"WARNING": 25, "ERROR": 1}


def test_a_run_opened_after_imports_names_that_time_startup():
    import time

    from immich_memories.db import open_store
    from immich_memories.tracking.run_observations import observe_run
    from immich_memories.tracking.span_progress import uncovered_seconds

    started = time.perf_counter() - 4.0
    with observe_run(open_store(), source="manual", capture_system=False, started=started) as run:
        pass
    spans = {span.name: span for span in _spans(run)}
    assert spans["startup"].duration >= 4.0
    assert spans["startup"].parent_id == spans["run"].span_id
    assert spans["run"].duration >= spans["startup"].duration
    assert uncovered_seconds(list(spans.values()), 0.0) < 0.5


def test_only_the_first_cli_run_of_a_process_claims_its_startup(monkeypatch):
    import time

    import click
    from click.testing import CliRunner

    from immich_memories import process_start
    from immich_memories.config_loader import Config
    from immich_memories.tracking.run_observations import current_tracker, observed_command

    # WHY: this test process began long before; a fresh mark stands in for a CLI that just did.
    monkeypatch.setattr(process_start, "_unclaimed", [time.perf_counter() - 2.0])
    runs = []

    @click.command()
    @click.pass_context
    @observed_command("manual")
    def command(ctx):
        runs.append(current_tracker())

    for _ in range(2):
        result = CliRunner().invoke(command, obj={"config": Config()}, catch_exceptions=False)
        assert result.exit_code == 0
    first, second = ({span.name for span in _spans(run)} for run in runs)
    assert "startup" in first
    assert "startup" not in second
