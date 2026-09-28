"""Spans use the same migrated store on both supported backends."""

from immich_memories.tracking import RunDatabase, RunTracker, timing
from immich_memories.tracking.span_store import SpanStore


def test_failed_run_spans_roundtrip_and_follow_run_deletion(store):
    tracker = RunTracker(store=store, capture_system=False)
    tracker.start_run(source="prepare")
    with timing.collecting() as collected, timing.span("preparation.detectors", items=4):
        pass
    spans = SpanStore(store)
    spans.save(tracker.run_id, collected)
    tracker.fail_run("detector unavailable")

    saved = spans.load(tracker.run_id)
    assert saved.spans[0].name == "preparation.detectors"
    assert saved.spans[0].items == 4
    assert saved.spans[0].duration >= 0
    RunDatabase(store).delete_run(tracker.run_id)
    assert spans.load(tracker.run_id).spans == []


def test_observed_prepare_persists_failure_and_warnings(store):
    import logging

    import pytest

    from immich_memories.tracking.run_observations import observe_run

    with (
        pytest.raises(ValueError, match="broken"),
        observe_run(store, source="prepare", capture_system=False) as tracker,
        timing.span("preparation.detectors", items=2),
    ):
        logging.getLogger("immich_memories.detector").warning("missing model")
        raise ValueError("broken")

    saved = RunDatabase(store).get_run(tracker.run_id)
    assert saved.status == "failed"
    assert saved.source == "prepare"
    assert "missing model" in saved.warnings
    assert SpanStore(store).load(tracker.run_id).spans[-1].error["type"] == "ValueError"


def test_matrix_attempt_keeps_the_same_saved_spans(store, tmp_path):
    import json

    from immich_memories.operations.run_index import record_run_attempt
    from immich_memories.tracking.run_observations import observe_run

    with observe_run(store, source="manual", capture_system=False) as tracker:
        record_run_attempt(tracker.run_id, tmp_path, "", store=store)
        with timing.span("preparation.detectors", items=8):
            pass

    exported = json.loads((tmp_path / "timings.private.json").read_text())
    assert exported == [span.to_dict() for span in SpanStore(store).load(tracker.run_id).spans]
