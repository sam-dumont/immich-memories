"""`--keep-intermediates` keeps the segments a film was cut from, beside the film (#2133).

FFmpeg cuts each segment into a private temp dir; closing the run deleted them whatever the
flag said. This cuts a real segment, closes the run with the flag on, and probes what was kept.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from immich_memories.config_loader import Config
from immich_memories.generate import _clear_run_intermediates
from immich_memories.processing.assembly_config import AssemblyClip
from immich_memories.processing.clips import extract_clip
from tests.integration.conftest import ffprobe_json, get_duration, requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]


def _cut(source) -> AssemblyClip:
    segment = extract_clip(source, start_time=0.5, end_time=2.5, config=Config())
    return AssemblyClip(path=segment, duration=2.0, asset_id="video")


def test_a_kept_run_holds_its_cut_segments(test_clip_720p, tmp_path):
    clip = _cut(test_clip_720p)
    run_folder = tmp_path / "run"
    run_folder.mkdir()

    _clear_run_intermediates(SimpleNamespace(debug_preserve_intermediates=True), [clip], run_folder)

    kept = run_folder / ".intermediates" / clip.path.name
    assert kept.is_file()
    assert not clip.path.exists()
    # A stream copy cuts on keyframes, so the segment runs a little past the asked 2 s.
    assert 1.5 < get_duration(ffprobe_json(kept)) < 3.0


def test_an_ordinary_run_leaves_no_segment_behind(test_clip_720p, tmp_path):
    clip = _cut(test_clip_720p)
    run_folder = tmp_path / "run"
    run_folder.mkdir()
    (run_folder / "film.mp4").write_bytes(b"film")

    _clear_run_intermediates(
        SimpleNamespace(debug_preserve_intermediates=False), [clip], run_folder
    )

    assert not clip.path.exists()
    assert sorted(p.name for p in run_folder.iterdir()) == ["film.mp4"]
