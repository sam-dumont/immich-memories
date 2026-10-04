"""A failed render keeps its resolved calendar scope for a saved-cut retry."""

from contextlib import nullcontext
from datetime import date, datetime

import pytest

from immich_memories.config_loader import Config
from immich_memories.db import open_store
from immich_memories.generate import GenerationError, GenerationParams, generate_memory
from immich_memories.tracking.run_database import RunDatabase
from immich_memories.tracking.run_observations import observe_run
from tests.conftest import make_clip


@pytest.mark.parametrize("observed", [False, True])
@pytest.mark.parametrize("as_datetime", [False, True])
def test_failed_render_keeps_february_scope(tmp_path, monkeypatch, observed, as_datetime):
    config = Config()
    config.title_screens.enabled = False
    store = open_store(config)
    start, end = date(2024, 2, 1), date(2024, 2, 29)
    if as_datetime:
        start, end = datetime(2024, 2, 1), datetime(2024, 2, 29, 23, 59, 59)
    params = GenerationParams(
        clips=[make_clip("february", duration=5)],
        config=config,
        output_path=tmp_path / "film.mp4",
        no_music=True,
        memory_type="monthly_highlights",
        date_start=start,
        date_end=end,
    )

    # Stop at the media boundary, after the real run/store lifecycle has recorded scope.
    def fail_extract(*args, **kwargs):
        raise RuntimeError("synthetic extraction failure")

    monkeypatch.setattr("immich_memories.generate_render.extract_clips", fail_extract)
    monkeypatch.setattr("immich_memories.tracking.run_tracker.capture_system_info", lambda: None)
    context = (
        observe_run(store, source="manual", capture_system=False) if observed else nullcontext()
    )
    with context, pytest.raises(GenerationError, match="synthetic extraction failure"):
        generate_memory(params)
    run = RunDatabase(store).list_runs(limit=1)[0]
    assert run.status == "failed"
    assert (run.date_range_start, run.date_range_end) == (date(2024, 2, 1), date(2024, 2, 29))


def test_a_render_stopped_midway_is_cancelled_and_leaves_no_scratch_folder(tmp_path, monkeypatch):
    config = Config()
    config.title_screens.enabled = False
    store = open_store(config)
    params = GenerationParams(
        clips=[make_clip("stopped", duration=5)],
        config=config,
        output_path=tmp_path / "film.mp4",
        no_music=True,
    )

    def stop_while_preparing(*args, **kwargs):
        scratch = next(tmp_path.glob("film_*")) / ".source_preparation" / "0"
        scratch.mkdir(parents=True)
        raise KeyboardInterrupt  # what a cancel from the UI becomes in the render's process

    # WHY: media extraction is the FFmpeg/Immich boundary; the run lifecycle stays real.
    monkeypatch.setattr("immich_memories.generate_render.extract_clips", stop_while_preparing)
    monkeypatch.setattr("immich_memories.tracking.run_tracker.capture_system_info", lambda: None)
    with pytest.raises(KeyboardInterrupt):
        generate_memory(params)

    run = RunDatabase(store).list_runs(limit=1)[0]
    assert run.status == "cancelled"
    assert not list(tmp_path.glob("film_*/.source_preparation"))
