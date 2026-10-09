"""Web job data stays private even before a media cache is opened."""

from __future__ import annotations

import json
import os
import stat
import sys
import time
from pathlib import Path

import pytest

from immich_memories.cli.progress_file import write_progress
from immich_memories.web.jobs import JobRunner
from immich_memories.web.server import storage_secret


def test_a_fresh_session_key_creates_private_parent_directories(tmp_path, monkeypatch):
    # WHY: isolate the account home and use a normal shared-machine umask.
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path))
    monkeypatch.delenv("IMMICH_MEMORIES_STORAGE_SECRET", raising=False)
    assert Path.home() == tmp_path
    original = os.umask(0o022)
    try:
        key = storage_secret()
    finally:
        os.umask(original)

    folder = tmp_path / ".immich-memories"
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    assert (folder / ".storage_secret").read_text() == key
    assert stat.S_IMODE((folder / ".storage_secret").stat().st_mode) == 0o600


def test_the_first_job_creates_private_directories_before_starting_its_child(tmp_path):
    cache = tmp_path / "fresh" / "cache"
    runner = JobRunner(cache)
    # The child sees the directory as it was when launched, before _save can repair it.
    script = "import os,stat,sys; print(oct(stat.S_IMODE(os.stat(sys.argv[1]).st_mode)))"
    original = os.umask(0o022)
    try:
        job = runner.start("cut", [sys.executable, "-c", script, str(cache / "web-jobs")])
    finally:
        os.umask(original)
    deadline = time.monotonic() + 10
    while runner.get(job.id).status == "running" and time.monotonic() < deadline:
        time.sleep(0.01)

    assert runner.get(job.id).status == "succeeded"
    assert runner.output(job.id).strip() == "0o700"
    for directory in (cache.parent, cache, cache / "web-jobs"):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700


@pytest.mark.parametrize("existing", [False, True])
def test_progress_is_private_even_inside_an_existing_shared_directory(tmp_path, existing):
    shared = tmp_path / "shared"
    shared.mkdir(mode=0o775)
    shared.chmod(0o775)
    progress = shared / "progress.json"
    if existing:
        progress.write_text('{"done": false}')
        progress.chmod(0o644)
    original = os.umask(0o022)
    try:
        write_progress(progress, {"done": True, "output_path": "/films/private-film.mp4"})
    finally:
        os.umask(original)

    assert stat.S_IMODE(progress.stat().st_mode) == 0o600
    assert stat.S_IMODE(shared.stat().st_mode) == 0o775
    record = json.loads(progress.read_text())
    assert record["done"] is True
    assert record["output_path"] == "/films/private-film.mp4"
    assert record["updated_at"] > 0
    assert list(shared.iterdir()) == [progress]


def test_existing_job_history_is_private_when_the_runner_reopens_it(tmp_path):
    shared = tmp_path / "shared"
    progress = shared / "web-jobs" / "progress" / ("a" * 32 + ".json")
    progress.parent.mkdir(parents=True)
    shared.chmod(0o775)
    progress.parent.parent.chmod(0o755)
    progress.parent.chmod(0o755)
    old_data = '{"done": true, "output_path": "/films/private-film.mp4"}'
    progress.write_text(old_data)
    progress.chmod(0o644)

    runner = JobRunner(shared)

    assert stat.S_IMODE((shared / "web-jobs").stat().st_mode) == 0o700
    assert stat.S_IMODE(shared.stat().st_mode) == 0o775
    assert runner.progress_path("a" * 32).read_text() == old_data
    assert runner.jobs() == []
