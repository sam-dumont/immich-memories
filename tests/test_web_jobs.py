"""The web client starts the CLI as a child process and follows it on disk."""

from __future__ import annotations

import json
import os
import subprocess
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

    secret = "oidc-client-secret-0f9e8d7c6b5a"  # noqa: S105 — synthetic
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


def _stale_running_record(tmp_path, pid: int, identity: str | None):
    """A job record a restarted server finds: still `running`, naming a pid that is now someone else's."""
    runner = JobRunner(tmp_path)
    job = runner.start("cut", [sys.executable, "-c", "pass"])
    _wait(runner, job.id)
    record = tmp_path / "web-jobs" / f"{job.id}.json"
    data = json.loads(record.read_text())
    data.update(status="running", finished_at=None, exit_code=None, pid=pid, pid_started=identity)
    record.write_text(json.dumps(data))
    return job.id


def test_a_reused_pid_does_not_keep_a_dead_job_running(tmp_path):
    """After a reboot the recorded pid can belong to any process; that must not 409 every new job."""
    job_id = _stale_running_record(tmp_path, os.getpid(), "started-before-the-reboot")
    restarted = JobRunner(tmp_path)

    assert restarted.get(job_id).status == "interrupted"
    assert restarted.active() is None
    restarted.start("cut", [sys.executable, "-c", "pass"])


def test_cancel_never_signals_a_process_the_job_did_not_start(tmp_path):
    bystander = subprocess.Popen(  # noqa: S603 - a sleeping child standing in for a reused pid
        [sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True
    )
    try:
        job_id = _stale_running_record(tmp_path, bystander.pid, "someone-else")

        cancelled = JobRunner(tmp_path).cancel(job_id)

        assert cancelled.status == "interrupted"
        time.sleep(0.2)
        assert bystander.poll() is None
    finally:
        bystander.kill()
        bystander.wait()


def test_cancelling_a_job_whose_pid_is_now_root_s_does_not_raise(tmp_path):
    job_id = _stale_running_record(tmp_path, 1, "someone-else")

    assert JobRunner(tmp_path).cancel(job_id).status == "interrupted"


def test_a_live_job_from_before_a_server_restart_can_still_be_cancelled(tmp_path):
    runner = JobRunner(tmp_path)
    job = runner.start("render", [sys.executable, "-c", "import time; time.sleep(30)"])

    restarted = JobRunner(tmp_path)
    assert restarted.get(job.id).status == "running"
    restarted.cancel(job.id)

    assert _wait(restarted, job.id).status in {"cancelled", "interrupted"}
    assert runner.get(job.id).status != "running"
