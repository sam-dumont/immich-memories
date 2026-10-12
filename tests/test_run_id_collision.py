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


def test_a_saved_render_whose_generated_id_is_taken_starts_under_a_fresh_one(tmp_path, monkeypatch):
    """`runs render` (the web client's export) records its own run: it must redraw too."""
    from immich_memories.generate import GenerationError, GenerationParams, generate_memory
    from tests.conftest import make_clip

    config = Config()
    config.title_screens.enabled = False
    store = open_store(config)
    taken = generate_run_id()
    running = RunTracker(taken, store=store, capture_system=False)
    running.start_run(source="auto")
    folders: list[str] = []

    def stop_at_extraction(*_args, **_kwargs):
        folders.extend(path.name for path in tmp_path.glob("film_*"))
        raise RuntimeError("synthetic extraction failure")

    # WHY: media extraction is the FFmpeg/Immich boundary; the run lifecycle stays real.
    monkeypatch.setattr("immich_memories.generate_render.extract_clips", stop_at_extraction)
    monkeypatch.setattr("immich_memories.tracking.run_tracker.capture_system_info", lambda: None)
    # WHY: the 16-bit suffix collides once in 65,536 same-second starts; force the collision.
    drawn = _ids(taken)
    monkeypatch.setattr("immich_memories.tracking.run_tracker.generate_run_id", drawn)
    params = GenerationParams(
        clips=[make_clip("render", duration=5)],
        config=config,
        output_path=tmp_path / "film.mp4",
        no_music=True,
    )

    with pytest.raises(GenerationError, match="synthetic extraction failure"):
        generate_memory(params)

    render = next(run for run in running.db.list_runs(limit=10) if run.run_id != taken)
    assert render.status == "failed"
    assert folders == [f"film_{render.run_id}"]
    still = running.db.get_run(taken)
    assert still is not None and still.status == "running"
    running.complete_run()
