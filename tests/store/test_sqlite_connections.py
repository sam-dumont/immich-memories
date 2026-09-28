"""Every raw SQLite connection the app opens gets the same safety settings."""

from __future__ import annotations

import stat
import threading
from contextlib import closing

import pytest

from immich_memories.db import NetworkFilesystemError, connect_sqlite


def _pragmas(connection) -> dict[str, object]:
    return {
        name: connection.execute(f"PRAGMA {name}").fetchone()[0]
        for name in ("journal_mode", "busy_timeout", "synchronous", "foreign_keys")
    }


def test_a_connection_runs_in_wal_with_a_long_busy_timeout(tmp_path):
    with closing(connect_sqlite(tmp_path / "a.db")) as connection:
        assert _pragmas(connection) == {
            "journal_mode": "wal",
            "busy_timeout": 30000,
            "synchronous": 1,  # NORMAL
            "foreign_keys": 1,
        }


def test_a_new_database_is_private_to_its_owner(tmp_path):
    path = tmp_path / "nested" / "a.db"
    with closing(connect_sqlite(path)) as connection:
        connection.execute("CREATE TABLE t (x)")
        connection.commit()

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_a_shared_database_keeps_its_permissions(tmp_path):
    path = tmp_path / "cache.db"
    path.touch(mode=0o644)
    path.chmod(0o644)

    connect_sqlite(path, private=False).close()

    assert stat.S_IMODE(path.stat().st_mode) == 0o644


def test_a_waiting_writer_gets_the_lock_once_the_holder_commits(tmp_path):
    path = tmp_path / "a.db"
    with closing(connect_sqlite(path, check_same_thread=False)) as holder:
        holder.execute("CREATE TABLE t (x)")
        holder.commit()
        holder.execute("BEGIN IMMEDIATE")
        holder.execute("INSERT INTO t VALUES (1)")
        released = threading.Timer(0.3, holder.commit)
        released.start()
        with closing(connect_sqlite(path)) as waiter:
            waiter.execute("INSERT INTO t VALUES (2)")
            waiter.commit()
            assert waiter.execute("SELECT count(*) FROM t").fetchone() == (2,)
        released.join()


def test_a_database_on_a_network_mount_is_refused(tmp_path, monkeypatch):
    monkeypatch.delenv("IMMICH_MEMORIES_ALLOW_NETWORK_SQLITE", raising=False)
    monkeypatch.setattr(
        "immich_memories.db.network_guard.system_mounts",
        # WHY: the network mount is simulated; CI has no NFS share to put a file on.
        lambda: (("/", "apfs"), (str(tmp_path.resolve()), "nfs")),
    )

    with pytest.raises(NetworkFilesystemError):
        connect_sqlite(tmp_path / "a.db")

    assert not (tmp_path / "a.db").exists()
