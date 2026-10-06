"""A run left `running` by a process that died reads interrupted; a live run never does."""

from __future__ import annotations

from datetime import UTC, datetime

from immich_memories.db.leases import Lease
from immich_memories.tracking.models import RunMetadata
from immich_memories.tracking.orphaned_runs import interrupt_orphaned_runs
from immich_memories.tracking.run_database import RunDatabase
from immich_memories.tracking.run_tracker import RunTracker

_T0 = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


def _save(db: RunDatabase, run_id: str, status: str) -> None:
    db.save_run(RunMetadata(run_id=run_id, created_at=_T0, status=status))  # type: ignore[arg-type]


def test_a_running_row_no_live_process_owns_reads_interrupted(store):
    db = RunDatabase(store)
    _save(db, "orphan", "running")
    _save(db, "done", "completed")

    interrupted = interrupt_orphaned_runs(store)

    assert interrupted == ["orphan"]
    orphan = db.get_run("orphan")
    assert orphan is not None and orphan.status == "interrupted"
    assert orphan.completed_at is not None
    done = db.get_run("done")
    assert done is not None and done.status == "completed"
    assert [r.run_id for r in db.list_runs(status="interrupted")] == ["orphan"]


def test_a_run_still_selecting_is_left_alone_though_no_render_holds_the_pipeline(store, tmp_path):
    """Discovery and selection run long before the render takes the pipeline lease."""
    db = RunDatabase(store)
    live = RunTracker(store=store, capture_system=False)
    live.start_run()
    _save(db, "orphan", "running")

    assert not Lease("pipeline", tmp_path / ".lock", store).held_elsewhere()
    assert interrupt_orphaned_runs(store) == ["orphan"]

    still = db.get_run(live.run_id)
    assert still is not None and still.status == "running"
    live.complete_run()


def test_a_live_render_does_not_shield_a_dead_run(store, tmp_path):
    db = RunDatabase(store)
    _save(db, "orphan", "running")

    with Lease("pipeline", tmp_path / ".lock", store):
        assert interrupt_orphaned_runs(store) == ["orphan"]


def test_a_run_its_tracker_ended_is_no_longer_held(store):
    db = RunDatabase(store)
    tracker = RunTracker(store=store, capture_system=False)
    tracker.start_run()
    tracker.fail_run("boom")

    assert interrupt_orphaned_runs(store) == []
    failed = db.get_run(tracker.run_id)
    assert failed is not None and failed.status == "failed"
