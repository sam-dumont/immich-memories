"""Progress bookkeeping does bounded work per tick: no full rewrite, no full re-read (#2689)."""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from immich_memories.analysis.sources.snapshot import SNAPSHOT_NAME, source_payload
from immich_memories.operations.attempt_size import ATTEMPT_SIZE
from immich_memories.operations.editorial_attempt import (
    REQUESTED_ASSETS,
    EditorialAttempt,
    read_editorial_attempt,
)
from immich_memories.operations.editorial_runs_budget import prune_editorial_runs
from immich_memories.web.job_stream import Seen, next_event
from immich_memories.web.jobs import JOB_RETENTION_SECONDS, JobRunner
from immich_memories.web.schemas import Job
from tests.conftest import make_asset
from tests.web_api_fixtures import api_client, config_in, save_run, selection_trace

# ---- 1. The request is written once; status updates stay small


def test_the_request_is_written_once_and_the_status_keeps_only_its_count(tmp_path):
    ids = [f"asset-{n:05d}" for n in range(5000)]
    with EditorialAttempt(tmp_path, request={"key": "k", "requested_assets": ids}) as attempt:
        status = attempt.directory / "status.private.json"
        for step in range(40):
            attempt.stage(f"Reading the period {step}")
        # 5000 ids would be 70 KB of it; the stage history is all that may grow, to a cap
        assert status.stat().st_size < 8192
        record = json.loads(status.read_text())["request"]
        assert "requested_assets" not in record
        assert record["requested_asset_count"] == 5000
        assert "\n" not in status.read_text()
        assert json.loads((attempt.directory / REQUESTED_ASSETS).read_text()) == ids
    assert (attempt.directory / REQUESTED_ASSETS).stat().st_size > 5000 * 10
    assert read_editorial_attempt(attempt.directory)["request"]["requested_asset_count"] == 5000


# ---- 2. The stream skips unchanged files and reuses a lease probe


def _render_job(runner, progress: Path) -> Job:
    return Job(
        id="a" * 32,
        kind="render",
        argv=["x"],
        started_at=time.time(),
        meta={"progress_file": str(progress)},
        status="running",
        pid=os.getpid(),
    )


def test_a_tick_with_no_changed_file_does_not_build_the_view_again(tmp_path):
    runner = JobRunner(tmp_path)
    progress = tmp_path / "progress.json"
    progress.write_text(json.dumps({"message": "Rendering", "fraction": 0.1}))
    job = _render_job(runner, progress)
    runner._save(job)
    seen = Seen(None, "")
    built = []

    def build(job):
        built.append(job.id)
        return json.dumps({"progress": progress.read_text()})

    def tick():
        return next_event(runner, runner.get(job.id), None, build, seen)

    seen, first, running = tick()
    seen, second, _ = tick()
    assert (len(built), second) == (1, None)
    assert first is not None and running
    progress.write_text(json.dumps({"message": "Rendering", "fraction": 0.5}))
    seen, third, _ = tick()
    assert len(built) == 2
    assert third is not None and "0.5" in third


def test_a_lease_probe_is_reused_within_its_window(tmp_path):
    # WHY: count the probes of the lease; the store behind a real one is not what is measured
    lease_patch = patch("immich_memories.operations.editorial_attempt._attempt_lease")
    with EditorialAttempt(tmp_path, request={}) as attempt, lease_patch as lease:
        lease.return_value.held_elsewhere.return_value = True
        for _ in range(50):
            read_editorial_attempt(attempt.directory, lease_ttl=5.0)
        assert lease.call_count == 1


# ---- 4. Run budgets are measured incrementally


def test_a_finished_attempt_is_not_walked_again_by_the_budget(tmp_path):
    from immich_memories.db import open_store

    root = tmp_path / "editorial-runs"
    with EditorialAttempt(root / "k", request={}) as attempt:
        attempt.complete(selected=1)
    (attempt.directory / "frames.bin").write_bytes(b"\0" * 10)
    # the size was noted at finish; the later file is not in it
    noted = json.loads((attempt.directory / ATTEMPT_SIZE).read_text())["size"]

    # WHY: count the directory walks the budget makes; nothing is replaced
    with patch("immich_memories.operations.editorial_runs_budget.walk_size") as walk:
        pruned = prune_editorial_runs(root, max_bytes=10**9, store=open_store())
    assert walk.call_count == 0
    assert pruned.removed == ()
    assert noted > 0


def test_an_attempt_from_before_the_note_is_walked_once_then_noted(tmp_path):
    from immich_memories.db import open_store

    root = tmp_path / "editorial-runs"
    with EditorialAttempt(root / "k", request={}) as attempt:
        attempt.complete(selected=1)
    note = attempt.directory / ATTEMPT_SIZE
    note.unlink()
    old = time.time() - 3 * 86400
    for path in (attempt.directory, *attempt.directory.iterdir()):
        os.utime(path, (old, old))

    prune_editorial_runs(root, max_bytes=10**9, store=open_store())

    assert note.is_file()
    with patch("immich_memories.operations.editorial_runs_budget.walk_size") as walk:
        prune_editorial_runs(root, max_bytes=10**9, store=open_store())
    assert walk.call_count == 0


# ---- 5. A pool page comes from a cached snapshot


def test_pool_pages_share_one_snapshot_read_until_a_file_changes(tmp_path):
    from immich_memories.web import pool

    config = config_in(tmp_path)
    attempt = save_run(config, "20260927_100000_f00d", trace=selection_trace())
    assets = [
        make_asset(f"p-{n}", file_created_at=datetime(2024, 6, 1 + n % 20, tzinfo=UTC))
        for n in range(30)
    ]
    snapshot = attempt / SNAPSHOT_NAME
    snapshot.write_text(json.dumps(source_payload(assets), default=str))
    client = api_client(config)
    pool._VIEWS.clear()

    with patch.object(pool, "sources_from_payload", wraps=pool.sources_from_payload) as parse:
        first = client.get("/api/v1/runs/20260927_100000_f00d/pool?limit=10").json()
        second = client.get("/api/v1/runs/20260927_100000_f00d/pool?offset=10&limit=10").json()
        assert parse.call_count == 1
        assert first["total"] == second["total"] == 30
        assert first["items"][0]["asset_id"] != second["items"][0]["asset_id"]
        snapshot.write_text(json.dumps(source_payload(assets[:5]), default=str))
        third = client.get("/api/v1/runs/20260927_100000_f00d/pool").json()
    assert parse.call_count == 2
    assert third["total"] == 5


def test_pool_holds_are_read_for_the_page_ids_only(tmp_path):
    from immich_memories.operations import picture_holds

    config = config_in(tmp_path)
    attempt = save_run(config, "20260927_100000_f00e", trace=selection_trace())
    assets = [
        make_asset(f"q-{n}", file_created_at=datetime(2024, 6, 1 + n, tzinfo=UTC))
        for n in range(12)
    ]
    (attempt / SNAPSHOT_NAME).write_text(json.dumps(source_payload(assets), default=str))

    with patch.object(picture_holds, "read", wraps=picture_holds.read) as read:
        api_client(config).get("/api/v1/runs/20260927_100000_f00e/pool?limit=4")
    assert len(read.call_args.args[1]) == 4


# ---- 6. Finished web jobs are pruned and not re-parsed


def _finish(runner: JobRunner, job_id: str) -> None:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        job = runner.get(job_id)
        if job and job.status != "running":
            return
        time.sleep(0.05)
    raise AssertionError("the child never finished")


def test_active_parses_a_finished_record_only_once(tmp_path):
    runner = JobRunner(tmp_path)
    job = runner.start("scan", [sys.executable, "-c", "pass"])
    _finish(runner, job.id)

    with patch.object(runner, "get", wraps=runner.get) as get:
        assert runner.active() is None
        first = get.call_count
        assert runner.active() is None
    assert first == 1
    assert get.call_count == first


def test_finished_jobs_past_the_retention_are_removed_with_their_files(tmp_path):
    runner = JobRunner(tmp_path)
    old = runner.start("scan", [sys.executable, "-c", "pass"])
    _finish(runner, old.id)
    fresh = runner.start("scan", [sys.executable, "-c", "pass"])
    _finish(runner, fresh.id)
    aged = time.time() - JOB_RETENTION_SECONDS - 60
    os.utime(runner._record(old.id), (aged, aged))

    assert runner.prune() == 1

    assert not runner._record(old.id).exists() and not runner.log_path(old.id).exists()
    assert runner._record(fresh.id).exists()
