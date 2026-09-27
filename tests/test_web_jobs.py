"""The web client starts the CLI as a child process and follows it on disk."""

from __future__ import annotations

import sys
import time

import pytest

from immich_memories.web.jobs import JobBusy, JobRunner


def _wait(runner: JobRunner, job_id: str, timeout: float = 20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = runner.get(job_id)
        if job is not None and job.status != "running":
            return job
        time.sleep(0.05)
    pytest.fail("the child never finished")


def test_a_job_runs_its_command_and_keeps_the_outcome_and_output(tmp_path):
    runner = JobRunner(tmp_path)
    job = runner.start("cut", [sys.executable, "-c", "print('selected 12 clips')"])

    finished = _wait(runner, job.id)

    assert finished.status == "succeeded" and finished.exit_code == 0
    assert "selected 12 clips" in runner.output(job.id)
    # A new runner (a restarted server) reads the same record from disk.
    assert JobRunner(tmp_path).get(job.id).status == "succeeded"


def test_a_failed_child_is_a_failed_job(tmp_path):
    runner = JobRunner(tmp_path)
    job = runner.start("cut", [sys.executable, "-c", "import sys; sys.exit(3)"])

    assert _wait(runner, job.id).status == "failed"


def test_only_one_job_runs_at_a_time_and_a_cancel_stops_it(tmp_path):
    runner = JobRunner(tmp_path)
    job = runner.start("render", [sys.executable, "-c", "import time; time.sleep(30)"])

    with pytest.raises(JobBusy) as busy:
        runner.start("cut", [sys.executable, "-c", "pass"])
    assert busy.value.job.id == job.id
    assert runner.active().id == job.id

    runner.cancel(job.id)

    assert _wait(runner, job.id).status == "cancelled"
    assert runner.active() is None


def test_a_job_s_progress_file_is_never_read_as_a_job(tmp_path):
    runner = JobRunner(tmp_path)
    job = runner.start("render", [sys.executable, "-c", "print('rendered')"])
    runner.progress_path(job.id).parent.mkdir(parents=True, exist_ok=True)
    runner.progress_path(job.id).write_text('{"done": true, "fraction": 1.0}')
    _wait(runner, job.id)

    assert runner.active() is None
    assert [listed.id for listed in runner.jobs()] == [job.id]
    # The next job starts: a render's progress beside the records once blocked every later job.
    runner.start("cut", [sys.executable, "-c", "pass"])
