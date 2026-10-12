"""Each run cuts into its own scratch directory, and a vanished shot stops the film (#2452)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from immich_memories import generate
from immich_memories import generate_render as generate_render_module
from immich_memories.config_loader import Config
from immich_memories.generate import GenerationError, GenerationParams
from immich_memories.generate_clips import cleanup_temp_clips, keep_temp_clips, new_run_scratch
from immich_memories.processing.assembly_config import AssemblyClip
from immich_memories.security import private_temp_dir
from tests.conftest import make_clip


def test_two_runs_get_two_private_scratch_directories():
    first, second = new_run_scratch(), new_run_scratch()
    try:
        assert first != second
        root = private_temp_dir("clips")
        assert first.parent == root and second.parent == root
        assert (first.stat().st_mode & 0o777) == 0o700
    finally:
        first.rmdir()
        second.rmdir()


def test_cleaning_one_run_leaves_the_other_runs_segment_and_drops_its_own_dir():
    mine, theirs = new_run_scratch(), new_run_scratch()
    same_name = "clip_f1f0674a_0.5_3.0.mp4"
    for directory in (mine, theirs):
        (directory / same_name).write_bytes(b"segment")
    try:
        cleanup_temp_clips([AssemblyClip(path=mine / same_name, duration=2.5)])

        assert not mine.exists()
        assert (theirs / same_name).read_bytes() == b"segment"
    finally:
        (theirs / same_name).unlink(missing_ok=True)
        theirs.rmdir()


def test_kept_segments_leave_an_empty_run_dir_behind_them(tmp_path):
    run = new_run_scratch()
    (run / "clip.mp4").write_bytes(b"segment")

    keep_temp_clips([AssemblyClip(path=run / "clip.mp4", duration=1.0)], tmp_path / "kept")

    assert (tmp_path / "kept" / "clip.mp4").read_bytes() == b"segment"
    assert not run.exists()


@pytest.fixture
def lost_shot(tmp_path, isolated_store):
    from immich_memories.db import open_store

    open_store()
    clips = [make_clip("garden-cake"), make_clip("garden-table")]
    config = Config(
        cache={
            "directory": str(tmp_path / "cache"),
            "database": str(tmp_path / "runs.db"),
            "video_cache_enabled": False,
        }
    )
    params = GenerationParams(
        clips=clips, output_path=tmp_path / "memory.mp4", config=config, no_music=True
    )
    kept = tmp_path / "kept.mp4"
    kept.write_bytes(b"segment")
    vanished = tmp_path / "vanished.mp4"  # prepared, then removed by something else
    return params, [
        AssemblyClip(path=kept, duration=2.0, asset_id="garden-cake"),
        AssemblyClip(path=vanished, duration=2.0, asset_id="garden-table"),
    ]


def test_a_shot_whose_file_vanished_stops_the_film_and_names_the_shot(lost_shot, monkeypatch):
    params, prepared = lost_shot
    # WHY: preparation is the boundary; it hands over one clip whose file is gone.
    monkeypatch.setattr(
        generate_render_module,
        "_extract_clips_with_optional_prefetch",
        lambda *_args, **_kw: list(prepared),
    )
    assembly = MagicMock(side_effect=AssertionError("a film one shot short reached assembly"))
    # WHY: assembly is the boundary that must never see the shortened cut.
    monkeypatch.setattr(generate_render_module, "create_assembler", assembly)

    with pytest.raises(GenerationError, match=r"disappeared before assembly \(garden-table\)"):
        generate.generate_memory(params)
    assembly.assert_not_called()
