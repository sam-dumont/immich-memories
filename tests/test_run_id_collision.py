"""Two runs that start in the same second must not collide on their id."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from immich_memories.config_loader import Config
from immich_memories.db import open_store
from immich_memories.tracking import RunTracker
from immich_memories.tracking.run_id import generate_run_id, is_valid_run_id
from immich_memories.tracking.run_lifecycle_errors import DuplicateRunError


def _ids(*values: str):
    """A run id generator that hands out these ids, then real ones."""
    queue = list(values)
    return lambda: queue.pop(0) if queue else generate_run_id()


@pytest.mark.parametrize("first_still_running", [True, False])
def test_a_run_whose_generated_id_is_taken_starts_under_a_fresh_one(first_still_running):
    store = open_store(Config())
    taken = generate_run_id()
    # WHY: the 16-bit suffix collides once in 65,536 same-second starts; force the collision.
    with patch("immich_memories.tracking.run_tracker.generate_run_id", _ids(taken, taken)):
        first = RunTracker(store=store, capture_system=False)
        first.start_run(source="manual")
        if not first_still_running:
            first.complete_run()
        second = RunTracker(store=store, capture_system=False)
        started = second.start_run(source="manual")

    assert first.run_id == taken
    assert started == second.run_id != taken
    assert is_valid_run_id(started)
    assert {run.run_id for run in second.db.list_runs(limit=10)} >= {taken, started}
    second.complete_run()
    if first_still_running:
        first.complete_run()


def test_a_run_id_the_caller_chose_is_never_replaced():
    store = open_store(Config())
    chosen = generate_run_id()
    RunTracker(chosen, store=store, capture_system=False).start_run(source="manual")

    with pytest.raises(DuplicateRunError):
        RunTracker(chosen, store=store, capture_system=False).start_run(source="manual")
