"""Elapsed event samples survive a process restart and the automation handoff."""

import sqlite3

from immich_memories.automation.state_store import AutomationStateStore
from immich_memories.config_loader import Config, set_config
from immich_memories.db import close_stores, open_store
from immich_memories.operations.phases import OperationalPhase, PhaseEvent
from immich_memories.operations.store_import import import_legacy
from immich_memories.tracking.models import RunMetadata
from immich_memories.tracking.run_database import RunDatabase
from immich_memories.tracking.run_tracker import RunTracker
from tests.legacy_cache_db import write_legacy_cache_db


def test_elapsed_samples_survive_reopen_and_mirror_only_the_linked_attempt(tmp_path):
    state = AutomationStateStore()
    attempt = state.start_attempt("daily wake")
    other = state.start_attempt("another wake")
    discovery = PhaseEvent(OperationalPhase.DISCOVERY, 1, 2, "Found a candidate", 2.5)
    state.update_phase(attempt.id, discovery)
    tracker = RunTracker("timed-run", capture_system=False)
    tracker.start_run(automation_attempt_id=attempt.id, source="auto")
    samples = [
        PhaseEvent(OperationalPhase.RENDER, 0, 2, "Starting render", 3.25),
        PhaseEvent(OperationalPhase.RENDER, 1, 2, "First clip rendered", 7.5),
    ]
    for event in samples:
        assert tracker.record_phase_event(event)
    assert not tracker.record_phase_event(discovery)
    assert not state.update_phase(attempt.id, discovery)
    tracker.fail_run("second clip failed")

    run = RunDatabase().get_run("timed-run")
    expected = [event.to_dict() for event in samples]
    assert run.phase_events == expected
    assert RunMetadata.from_dict(run.to_dict()).phase_events == expected
    close_stores()
    reopened = AutomationStateStore()
    assert reopened.get_attempt(attempt.id).phase_events == [discovery.to_dict(), *expected]
    assert reopened.get_attempt(other.id).phase_events == []


def test_import_preserves_old_rows_without_inventing_elapsed_samples(tmp_path, monkeypatch):
    path = tmp_path / "v23.db"
    write_legacy_cache_db(path, version=23)
    with sqlite3.connect(path) as conn:
        conn.execute("""INSERT INTO pipeline_runs (run_id, created_at, status, last_phase)
                        VALUES ('old-run', '2026-08-12T08:00:00+00:00', 'failed', 'render')""")
        conn.execute("""INSERT INTO automation_attempts (id, started_at, outcome, reason, last_phase)
                        VALUES ('old-attempt', '2026-08-12T08:00:00+00:00', 'failed',
                                'daily wake', 'render')""")
    set_config(Config(cache={"database": str(path), "directory": str(tmp_path / "cache")}))
    import_legacy(open_store(), tmp_path)
    run = RunDatabase().get_run("old-run")
    attempt = AutomationStateStore().get_attempt("old-attempt")
    assert run.status == "failed"
    assert run.last_phase is attempt.last_phase is OperationalPhase.RENDER
    assert run.phase_events == attempt.phase_events == []
