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


def test_a_finished_child_whose_result_cannot_be_read_ends_failed_not_running(tmp_path):
    runner = JobRunner(tmp_path)

    def unreadable(_job):
        raise ValueError("half-written progress file")

    job = runner.start("render", [sys.executable, "-c", "pass"], on_finish=unreadable)

    finished = _wait(runner, job.id, timeout=5)
    assert finished.status == "failed" and finished.exit_code == 0
    assert runner.active() is None


@pytest.mark.parametrize("job_id", ["../outside", "/tmp/outside", "bad/id", "bad\\id"])
def test_job_paths_refuse_ids_outside_the_job_namespace(tmp_path, job_id):
    runner = JobRunner(tmp_path)
    for operation in (runner.get, runner.output, runner.progress_path, runner.cancel):
        with pytest.raises(ValueError, match="Invalid job ID"):
            operation(job_id)
    with pytest.raises(ValueError, match="Invalid job ID"):
        runner.start("cut", [sys.executable, "-c", "pass"], job_id=job_id)


def test_job_files_cannot_follow_symlinks_outside_the_cache(tmp_path):
    runner = JobRunner(tmp_path / "cache")
    job_id = "a" * 32
    directory = tmp_path / "cache" / "web-jobs"
    directory.mkdir(parents=True)
    outside = tmp_path / "outside.json"
    outside.write_text('{"private": true}')
    (directory / f"{job_id}.json").symlink_to(outside)
    with pytest.raises(ValueError, match="Invalid job ID"):
        runner.get(job_id)
    (directory / f"{job_id}.log").symlink_to(outside)
    with pytest.raises(ValueError, match="Invalid job ID"):
        runner.output(job_id)
    (directory / "progress").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="Invalid job ID"):
        runner.progress_path(job_id)


def test_job_output_hides_every_configured_secret(tmp_path):
    from immich_memories.config_loader import Config, set_config

    secret = "oidc-client-secret-0f9e8d7c6b5a"
    config = Config()
    config.auth.client_secret = secret
    set_config(config)
    try:
        runner = JobRunner(tmp_path)
        job = runner.start("cut", [sys.executable, "-c", f"print('signing in with {secret}')"])
        _wait(runner, job.id)

        output = runner.output(job.id)
    finally:
        set_config(None)

    assert secret not in output
    assert "signing in with ***" in output
