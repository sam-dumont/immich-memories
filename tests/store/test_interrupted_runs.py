"""A run left `running` by a process that died is marked interrupted at the next start."""

from __future__ import annotations

from datetime import UTC, datetime

from immich_memories.db.leases import Lease
from immich_memories.tracking.models import RunMetadata
from immich_memories.tracking.orphaned_runs import interrupt_orphaned_runs
from immich_memories.tracking.run_database import RunDatabase

_T0 = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


def _save(db: RunDatabase, run_id: str, status: str) -> None:
    db.save_run(RunMetadata(run_id=run_id, created_at=_T0, status=status))  # type: ignore[arg-type]


def test_a_running_row_with_no_live_pipeline_reads_interrupted(store, tmp_path):
    db = RunDatabase(store)
    _save(db, "orphan", "running")
    _save(db, "done", "completed")

    interrupted = interrupt_orphaned_runs(store, tmp_path / ".lock")

    assert interrupted == ["orphan"]
    orphan = db.get_run("orphan")
    assert orphan is not None and orphan.status == "interrupted"
    assert orphan.completed_at is not None
    done = db.get_run("done")
    assert done is not None and done.status == "completed"
    assert [r.run_id for r in db.list_runs(status="interrupted")] == ["orphan"]


def test_a_running_row_is_left_alone_while_a_pipeline_holds_the_lease(store, tmp_path):
    db = RunDatabase(store)
    _save(db, "live", "running")
    lock = tmp_path / ".lock"

    with Lease("pipeline", lock, store):
        assert interrupt_orphaned_runs(store, lock) == []

    live = db.get_run("live")
    assert live is not None and live.status == "running"
