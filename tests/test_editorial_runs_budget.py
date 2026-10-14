"""editorial-runs stays inside its budget without losing what a listed run reads (#2528)."""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from immich_memories.db import open_store
from immich_memories.operations.editorial_attempt import EditorialAttempt
from immich_memories.operations.editorial_runs_budget import prune_editorial_runs
from immich_memories.operations.run_index import attempt_dir_for_run, record_run_attempt
from immich_memories.tracking import RunDatabase
from immich_memories.tracking.models import RunMetadata

_MB = 1_000_000


def _attempt(root: Path, key: str, *, megabytes: int, days_old: float, status="complete"):
    """A finished attempt on disk with `megabytes` of frames, last touched `days_old` ago."""
    with EditorialAttempt(root / key, request={"key": key}) as attempt:
        if status == "complete":
            attempt.complete(selected=3)
    (attempt.directory / "frames.bin").write_bytes(b"\0" * megabytes * _MB)
    then = time.time() - days_old * 86400
    for path in (attempt.directory, *attempt.directory.iterdir()):
        os.utime(path, (then, then))
    return attempt.directory


def _listed_run(store, run_id: str, attempt_dir: Path) -> None:
    RunDatabase(store).save_run(
        RunMetadata(run_id=run_id, created_at=datetime.now(UTC), status="completed")
    )
    record_run_attempt(run_id, attempt_dir, "", store=store)


@pytest.fixture
def store():
    return open_store()


@pytest.mark.feature("storage.editorial-runs-capped")
def test_unread_attempts_go_first_and_a_listed_runs_attempt_stays(tmp_path, store):
    root = tmp_path / "editorial-runs"
    failed = _attempt(root, "month-a", megabytes=3, days_old=9, status="failed")
    read = _attempt(root, "month-a", megabytes=3, days_old=8)
    superseded = _attempt(root, "month-b", megabytes=3, days_old=7)
    newest_b = _attempt(root, "month-b", megabytes=3, days_old=6)
    newest_a = _attempt(root, "month-a", megabytes=3, days_old=5)
    _listed_run(store, "20260101_000000_aaaa", read)

    pruned = prune_editorial_runs(root, max_bytes=10 * _MB, store=store)

    assert set(pruned.removed) == {failed, superseded}
    assert read.exists() and newest_a.exists() and newest_b.exists()
    assert attempt_dir_for_run("20260101_000000_aaaa", store=store) == read
    assert pruned.overflow_bytes == 0


def test_under_budget_nothing_is_touched(tmp_path, store):
    root = tmp_path / "editorial-runs"
    old = _attempt(root, "month-a", megabytes=1, days_old=30, status="failed")
    _attempt(root, "month-a", megabytes=1, days_old=1)

    assert prune_editorial_runs(root, max_bytes=10 * _MB, store=store).removed == ()
    assert old.exists()


def test_a_listed_runs_attempt_goes_only_when_nothing_unread_is_left_oldest_first(tmp_path, store):
    root = tmp_path / "editorial-runs"
    oldest = _attempt(root, "year", megabytes=4, days_old=40)
    older = _attempt(root, "year", megabytes=4, days_old=20)
    _attempt(root, "year", megabytes=4, days_old=3)
    _listed_run(store, "20260101_000000_bbbb", oldest)
    _listed_run(store, "20260201_000000_cccc", older)

    pruned = prune_editorial_runs(root, max_bytes=9 * _MB, store=store)

    assert pruned.removed == (oldest,)
    assert older.exists()


def test_a_deleted_runs_attempt_is_unread(tmp_path, store):
    root = tmp_path / "editorial-runs"
    orphan = _attempt(root, "trip", megabytes=4, days_old=40)
    listed = _attempt(root, "trip", megabytes=4, days_old=50)
    _attempt(root, "trip", megabytes=4, days_old=3)
    _listed_run(store, "20260101_000000_dddd", orphan)
    _listed_run(store, "20260101_000000_eeee", listed)
    RunDatabase(store).delete_run("20260101_000000_dddd")

    pruned = prune_editorial_runs(root, max_bytes=9 * _MB, store=store)

    assert pruned.removed == (orphan,)


def test_live_recent_and_newest_attempts_stay_even_over_budget(tmp_path, store):
    root = tmp_path / "editorial-runs"
    newest = _attempt(root, "lifetime", megabytes=4, days_old=60)
    recent = _attempt(root, "month", megabytes=2, days_old=0.1)
    _attempt(root, "month", megabytes=2, days_old=0)  # newest of its key
    with EditorialAttempt(root / "lifetime", request={}) as live:
        (live.directory / "frames.bin").write_bytes(b"\0" * 4 * _MB)
        long_ago = time.time() - 30 * 86400
        for path in (live.directory, *live.directory.iterdir()):
            os.utime(path, (long_ago, long_ago))
        # The live attempt took the pointer; the 60-day-old one is neither live nor newest.
        pruned = prune_editorial_runs(root, max_bytes=1 * _MB, store=store)
        assert live.directory.exists()

    assert pruned.removed == (newest,)
    assert recent.exists()
    assert pruned.overflow_bytes > 0


def _sparse(path, size: int) -> None:
    """A file of `size` bytes that takes no disk."""
    with path.open("wb") as handle:
        handle.truncate(size)


def test_a_run_start_holds_the_folder_to_the_configured_key(tmp_path, store):
    """The key a user sets is the budget; sparse frames stand in for a real attempt's weight."""
    from immich_memories.config_loader import Config
    from immich_memories.operations.editorial_runs_budget import keep_editorial_runs_in_budget

    config = Config()
    config.cache.directory = str(tmp_path / "cache")
    config.cache.editorial_runs_max_size_gb = 0.5
    root = config.cache.cache_path / "editorial-runs"
    old = _attempt(root, "month", megabytes=0, days_old=10, status="failed")
    _sparse(old / "frames.bin", 400 * 1024**2)
    newest = _attempt(root, "month", megabytes=0, days_old=2)
    _sparse(newest / "frames.bin", 400 * 1024**2)

    assert keep_editorial_runs_in_budget(config, store=store).removed == (old,)
