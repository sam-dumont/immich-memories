"""A full data volume must not leave the browser following a dead child forever."""

import errno
import json
import sys
import time

import pytest

from immich_memories.web.job_routes import job_runner
from immich_memories.web.jobs import JobRunner
from immich_memories.web.schemas import Job
from tests.web_api_fixtures import api_client, config_in


def test_failed_child_reaches_browser_even_when_final_record_cannot_be_saved(tmp_path, monkeypatch):
    config = config_in(tmp_path)
    runner = JobRunner(config.cache.cache_path)
    client = api_client(config)
    client.app.dependency_overrides[job_runner] = lambda: runner
    gate = tmp_path / "finish-child"
    job = runner.start(
        "cut",
        [
            sys.executable,
            "-c",
            (
                "import pathlib,sys,time\n"
                f"while not pathlib.Path({str(gate)!r}).exists(): time.sleep(0.01)\n"
                "sys.exit(7)\n"
            ),
        ],
    )

    def full_disk(*_args, **_kwargs):
        raise OSError(errno.ENOSPC, "No space left on device", "/private/storage/job.json")

    # WHY: the filesystem refuses writes after the real child starts; no disk is filled.
    monkeypatch.setattr("immich_memories.web.jobs.write_secret_file", full_disk)
    gate.touch()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/jobs/{job.id}")
        assert response.status_code == 200
        result = response.json()
        if result["status"] != "running":
            break
        time.sleep(0.02)
    else:
        raise AssertionError("The browser never received the child's failure")

    assert result["status"] == "failed"
    assert result["exit_code"] == 7
    assert "storage is full" in result["error"].lower()
    assert "/private/storage" not in result["error"]
    assert client.get("/api/v1/jobs/active").json() is None
    events = client.get(f"/api/v1/jobs/{job.id}/events")
    assert '"status":"failed"' in events.text
    assert "storage is full" in events.text.lower()


@pytest.mark.parametrize("code", [errno.ENOSPC, errno.EDQUOT, errno.EACCES])
def test_orphaned_job_is_readable_and_saved_when_storage_recovers(tmp_path, monkeypatch, code):
    root = tmp_path / "web-jobs"
    root.mkdir()
    job = Job(id="b" * 32, kind="cut", argv=[], started_at=1)
    record = root / f"{job.id}.json"
    record.write_text(job.model_dump_json())

    def refused(*_args, **_kwargs):
        raise OSError(code, "private diagnostic", "/private/storage/record")

    runner = JobRunner(tmp_path)
    with monkeypatch.context() as patch:
        # WHY: a restarted server can read the old job record but still cannot update it.
        patch.setattr("immich_memories.web.jobs.write_secret_file", refused)
        ended = runner.get(job.id)
        assert ended.status == "interrupted"
        assert ended.error and "private" not in ended.error
        assert runner.active() is None
        assert runner.jobs()[0].status == "interrupted"
        assert json.loads(record.read_text())["status"] == "running"
    assert runner.get(job.id).status == "interrupted"
    assert JobRunner(tmp_path).get(job.id).error == ended.error


def test_cancel_still_stops_the_child_when_status_storage_is_full(tmp_path, monkeypatch):
    runner = JobRunner(tmp_path)
    job = runner.start("cut", [sys.executable, "-c", "import time; time.sleep(30)"])

    def full(*_args, **_kwargs):
        raise OSError(errno.ENOSPC, "full")

    # WHY: cancellation must signal the real process even when its record cannot be saved.
    monkeypatch.setattr("immich_memories.web.jobs.write_secret_file", full)
    try:
        runner.cancel(job.id)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            ended = runner.get(job.id)
            if ended.status != "running":
                break
            time.sleep(0.02)
        assert ended.status == "cancelled"
        assert "Storage is full" in ended.error
    finally:
        import os
        import signal
        from contextlib import suppress

        with suppress(ProcessLookupError):
            os.killpg(job.pid, signal.SIGTERM)


def test_result_read_failure_is_reported_even_when_the_log_cannot_be_written(tmp_path, monkeypatch):
    from pathlib import Path

    original_open = Path.open

    def no_log_space(path, mode="r", *args, **kwargs):
        if path.suffix == ".log" and mode == "a":
            raise OSError(errno.ENOSPC, "full")
        return original_open(path, mode, *args, **kwargs)

    def unreadable(_job):
        raise ValueError("private result data")

    # WHY: the error-log append is a separate filesystem failure from reading the result.
    monkeypatch.setattr(Path, "open", no_log_space)
    runner = JobRunner(tmp_path)
    job = runner.start("cut", [sys.executable, "-c", "pass"], on_finish=unreadable)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        ended = runner.get(job.id)
        if ended.status != "running":
            break
        time.sleep(0.02)
    assert ended.status == "failed"
    assert "result could not be read" in ended.error
    assert "Storage is full" in ended.error
    assert "private result data" not in ended.error
