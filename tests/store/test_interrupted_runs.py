"""A run left `running` by a process that died reads interrupted; a live run never does."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

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


@pytest.mark.feature("web.server-small-fixes")
def test_a_run_that_cannot_take_its_lease_does_not_start_to_be_swept_as_dead(store):
    """No owner label means the sweep would end a live run and refuse its later `complete`."""
    tracker = RunTracker(store=store, capture_system=False)

    # WHY: a failing lock directory or advisory-lock connection is a storage boundary.
    with (
        patch.object(Lease, "acquire", side_effect=OSError("no space left")),
        pytest.raises(RuntimeError, match="liveness lease"),
    ):
        tracker.start_run()

    assert interrupt_orphaned_runs(store) == []
    assert RunDatabase(store).running_run_ids() == []


def test_a_run_whose_id_another_start_has_just_leased_is_not_written_unowned(store):
    """Two same-second starts drew one id; the other took its lease first and gave it up.

    The other start held the id's lease between taking it and finding the row taken. A start
    that wrote the row without the lease left a live run with no owner: the next sweep ended
    it while it worked, and its `complete` then rewrote the interrupted row.
    """
    from immich_memories.tracking.run_id import generate_run_id

    drawn = generate_run_id()
    ids = [drawn]
    other_start = RunDatabase(store).run_lease(drawn)
    other_start.acquire()
    # WHY: the 16-bit suffix collides once in 65,536 same-second starts; force the collision.
    with patch(
        "immich_memories.tracking.run_tracker.generate_run_id",
        lambda: ids.pop(0) if ids else generate_run_id(),
    ):
        live = RunTracker(store=store, capture_system=False)
        live.start_run(source="manual")
    other_start.release()

    assert interrupt_orphaned_runs(store) == []
    assert live.run_id != drawn
    saved = RunDatabase(store).get_run(live.run_id)
    assert saved is not None and saved.status == "running"
    live.complete_run()
