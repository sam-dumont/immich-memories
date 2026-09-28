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
