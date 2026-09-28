"""The SQLite files the app still writes all go through the one connection factory (#871 P0).

WAL is persistent in the file header, and SQLite deletes the `-wal` sidecar when the last
connection closes: a WAL database with no sidecar left behind was opened right and closed.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from immich_memories.cache.database import VideoAnalysisCache
from immich_memories.cache.sqlite_conn import ThreadOwnedConnections


def _journal_mode(path: Path) -> str:
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute("PRAGMA journal_mode").fetchone()[0]


def _left_open(path: Path) -> bool:
    return Path(f"{path}-wal").exists()


def test_the_analysis_cache_opens_in_wal_and_closes(tmp_path):
    path = tmp_path / "cache.db"
    VideoAnalysisCache(path).clear_all()

    assert _journal_mode(path) == "wal"
    assert not _left_open(path)


def test_thread_owned_caches_open_in_wal(tmp_path):
    path = tmp_path / "scene-prints.sqlite"
    connections = ThreadOwnedConnections(path, "CREATE TABLE IF NOT EXISTS prints (key TEXT)")
    with connections.connection() as connection:
        connection.execute("INSERT INTO prints VALUES ('k')")
        connection.commit()

    assert _journal_mode(path) == "wal"
    connections.close()
