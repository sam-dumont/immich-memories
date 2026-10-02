"""A full filesystem must not leave a running child or a published partial revision."""

import errno
import json
import os
import sys

import pytest

from immich_memories.operations.cut_revisions import CutEdits, read_revisions, save_revision
from immich_memories.web.jobs import JobRunner
from tests.web_api_fixtures import api_client, config_in, save_run


def test_a_job_whose_initial_record_cannot_be_saved_stops_its_child(tmp_path, monkeypatch):
    from immich_memories.web import jobs

    launched = []

    def full(_path, value):
        # WHY: inject a full disk at the record write, after the real child starts.
        launched.append(json.loads(value)["pid"])
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(jobs, "write_secret_file", full)
    runner = JobRunner(tmp_path)
    with pytest.raises(OSError):
        runner.start("cut", [sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        with pytest.raises(ProcessLookupError):
            os.kill(launched[0], 0)
    finally:
        try:
            os.kill(launched[0], 9)
        except ProcessLookupError:
            pass


def test_a_failed_revision_publish_keeps_earlier_edits_and_removes_the_temporary(
    tmp_path, monkeypatch
):
    from immich_memories.operations import cut_revisions

    config = config_in(tmp_path)
    folder = save_run(config, "storage-check")
    assert folder is not None
    saved = save_revision(folder, CutEdits())

    def full(_source, _target):
        # WHY: the atomic filesystem publication is the failing write boundary.
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(cut_revisions.os, "replace", full)
    with pytest.raises(OSError):
        save_revision(folder, CutEdits(removed=("lake-1",)))
    assert read_revisions(folder) == [saved]
    assert not list((folder / "revisions").glob("*.tmp"))


def test_a_full_music_disk_returns_a_clear_retryable_error(tmp_path, monkeypatch):
    from pathlib import Path

    from tests.generated_audio_fixtures import write_audio

    config = config_in(tmp_path)
    client = api_client(config)
    track = tmp_path / "valid.wav"
    write_audio(track, 0.1)
    payload = track.read_bytes()

    def full(_path, _data):
        # WHY: emulate ENOSPC at the upload write without filling the developer's disk.
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(Path, "write_bytes", full)
    response = client.post("/api/v1/music", files={"file": ("valid.wav", payload, "audio/wav")})
    assert response.status_code == 507
    assert "space" in response.json()["detail"].lower()
    assert not list((config.cache.cache_path / "web-music").glob("*"))
