"""A cut killed half-way is never reused as the next run's segment (#2348).

Segments are cut into a shared scratch dir and reused by name. FFmpeg killed mid-write
left a file with no moov atom under that name; the next run took it as finished, and
its film failed reading the clip.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from immich_memories.config_loader import Config
from immich_memories.processing.clips import extract_clip
from tests.integration.conftest import requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]


def _ffmpeg_killed_mid_write(folder: Path) -> Path:
    """An `ffmpeg` that writes its output, then leaves only the first third, as a kill does."""
    folder.mkdir()
    shim = folder / "ffmpeg"
    shim.write_text(
        "#!/bin/sh\n"
        f'"{shutil.which("ffmpeg")}" "$@"\n'
        "for last; do :; done\n"
        f'"{sys.executable}" -c "import os,sys; p=sys.argv[1]; '
        'os.truncate(p, os.path.getsize(p) // 3)" "$last"\n'
        "exit 255\n"
    )
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
    return folder


def _plays(path: Path) -> bool:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0"]
        + [str(path)],
        capture_output=True,
        text=True,
    )
    return probe.returncode == 0 and "video" in probe.stdout


@pytest.mark.feature("render.media-small-fixes")
def test_the_cut_after_a_killed_one_is_whole(test_clip_720p, tmp_path, monkeypatch):
    # WHY: the shared scratch lives in the temp dir; keep this test's cuts to itself.
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    shim = _ffmpeg_killed_mid_write(tmp_path / "killed")
    monkeypatch.setenv("PATH", f"{shim}{os.pathsep}{os.environ['PATH']}")

    with pytest.raises(RuntimeError):
        extract_clip(test_clip_720p, start_time=0.5, end_time=2.5, config=Config())
    monkeypatch.undo()
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))

    segment = extract_clip(test_clip_720p, start_time=0.5, end_time=2.5, config=Config())

    assert _plays(segment)
