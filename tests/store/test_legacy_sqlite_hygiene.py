"""The SQLite files the app writes today all go through the one connection factory (#871 P0).

WAL is persistent in the file header, and SQLite deletes the `-wal` sidecar when the last
connection closes: a WAL database with no sidecar left behind was opened right and closed.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from immich_memories.cache.database import VideoAnalysisCache
from immich_memories.cache.editorial_verdicts import EditorialVerdicts
from immich_memories.cache.judgment_cache import JudgmentCache
from immich_memories.store import owner_decisions
from immich_memories.store.cut_measurements import open_cut_measurements, remember_motion_residual


def _journal_mode(path: Path) -> str:
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute("PRAGMA journal_mode").fetchone()[0]


def _left_open(path: Path) -> bool:
    return Path(f"{path}-wal").exists()


def test_editorial_verdicts_write_in_wal_and_close_their_connection(tmp_path):
    path = tmp_path / "annotations.sqlite"
    verdicts = EditorialVerdicts(path)
    version = "cull-v1"
    verdicts.remember([("a", "kept")], pass_version=version)

    assert verdicts.recall(["a"], pass_version=version) == {"a": "kept"}
    assert _journal_mode(path) == "wal"
    assert not _left_open(path)


def test_owner_decisions_write_in_wal_and_close(tmp_path):
    path = tmp_path / "annotations.sqlite"
    owner_decisions.decide(path, "a", owner_decisions.NEVER_USE, via="cli", clip_id="a")

    assert _journal_mode(path) == "wal"
    assert not _left_open(path)


def test_cut_measurements_open_in_wal(tmp_path):
    path = tmp_path / "annotations.sqlite"
    with closing(open_cut_measurements(path)) as connection:
        remember_motion_residual(
            connection, asset_id="a", producer="p", source_digest="d", measured={"r": 1.0}
        )
        assert connection.execute("PRAGMA busy_timeout").fetchone() == (30000,)

    assert _journal_mode(path) == "wal"


def test_the_analysis_cache_opens_in_wal_and_closes(tmp_path):
    path = tmp_path / "cache.db"
    VideoAnalysisCache(path).clear_all()

    assert _journal_mode(path) == "wal"
    assert not _left_open(path)


def test_thread_owned_caches_open_in_wal(tmp_path):
    path = tmp_path / "judgments.db"
    cache = JudgmentCache(path)
    cache.remember("k", "yes")

    assert cache.answer_for("k") == "yes"
    assert _journal_mode(path) == "wal"
    cache.close()
