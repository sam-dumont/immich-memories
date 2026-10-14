"""A killed run's scratch is swept by the next start; a live run's never is (#2528)."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from immich_memories.security import runtime_scratch

_HOURS = 3600

# A child that takes the scratch the way the CLI does, leaves a frame in it, says where,
# then either dies without cleaning up (SIGKILL, like an OOM kill) or waits to be killed.
_CHILD = """
import os, signal, sys, tempfile
from pathlib import Path
from immich_memories.security import runtime_scratch
with runtime_scratch(Path(sys.argv[1])):
    frames = Path(tempfile.mkdtemp(prefix="immich-detector-frames-"))
    (frames / "detector-00.jpg").write_bytes(b"synthetic frame")
    print(tempfile.gettempdir(), flush=True)
    if sys.argv[2] == "die":
        os.kill(os.getpid(), signal.SIGKILL)
    sys.stdin.read()
"""


def _age(path: Path, hours: float) -> None:
    then = time.time() - hours * _HOURS
    os.utime(path, (then, then))


def _child(cache: Path, mode: str) -> tuple[subprocess.Popen[str], Path]:
    child = subprocess.Popen(  # noqa: S603 - our own interpreter on a fixed script
        [sys.executable, "-c", _CHILD, str(cache), mode],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert child.stdout is not None
    return child, Path(child.stdout.readline().strip())


def test_each_process_gets_its_own_folder_inside_the_scratch(tmp_path):
    cache = tmp_path / "cache"
    with runtime_scratch(cache) as scratch:
        own = Path(tempfile.gettempdir())
        assert own.parent == scratch
        assert own.stat().st_mode & 0o777 == 0o700
        with runtime_scratch(cache):
            assert Path(tempfile.gettempdir()) != own
        assert Path(tempfile.gettempdir()) == own


@pytest.mark.feature("storage.scratch-swept")
def test_a_killed_runs_scratch_is_swept_at_the_next_start(tmp_path):
    cache = tmp_path / "cache"
    child, leftover = _child(cache, "die")
    assert child.wait(timeout=60) == -signal.SIGKILL
    assert any(leftover.glob("immich-detector-frames-*"))
    _age(leftover, 2)

    with runtime_scratch(cache):
        assert not leftover.exists()


@pytest.mark.feature("storage.scratch-swept")
def test_a_live_runs_scratch_survives_another_start(tmp_path):
    cache = tmp_path / "cache"
    child, live = _child(cache, "wait")
    try:
        _age(live, 48)
        with runtime_scratch(cache):
            assert any(live.glob("immich-detector-frames-*/detector-00.jpg"))
    finally:
        child.kill()
        child.wait(timeout=60)


def test_a_folder_freed_moments_ago_is_left_for_a_later_start(tmp_path):
    """A process that just ended may have handed a file to its parent; the grace lets it."""
    cache = tmp_path / "cache"
    child, leftover = _child(cache, "die")
    child.wait(timeout=60)

    with runtime_scratch(cache):
        assert leftover.exists()


def test_scratch_from_before_ownership_goes_once_it_is_a_day_old(tmp_path):
    cache = tmp_path / "cache"
    scratch = cache / "scratch"
    scratch.mkdir(parents=True, mode=0o700)
    old_frames = cache / "immich-detector-frames-x1y2z3"
    old_frames.mkdir()
    (old_frames / "vv1").mkdir()
    (old_frames / "vv1" / "detector-00.jpg").write_bytes(b"synthetic frame")
    fresh_frames = cache / "immich-detector-frames-a1b2c3"
    fresh_frames.mkdir()
    old_loose = scratch / "looped_music_x1.mp3"
    old_loose.write_bytes(b"synthetic audio")
    fresh_loose = scratch / "looped_music_a1.mp3"
    fresh_loose.write_bytes(b"synthetic audio")
    kept_cache = cache / "thumbnails"
    kept_cache.mkdir()
    for path in (old_frames, old_loose, kept_cache):
        _age(path, 30)

    with runtime_scratch(cache):
        pass

    assert not old_frames.exists()
    assert not old_loose.exists()
    assert fresh_frames.exists()
    assert fresh_loose.exists()
    assert kept_cache.exists()
