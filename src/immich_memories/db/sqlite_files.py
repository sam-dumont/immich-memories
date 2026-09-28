"""The one way the app opens a SQLite file, for raw `sqlite3` users and the store engine alike.

Every connection runs in WAL with a 30 s busy timeout, `synchronous=NORMAL` and foreign keys
on, after the network-filesystem guard has passed. Before this, each module picked its own:
a 5 s timeout here, no WAL there, and one connection that was never closed.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
from pathlib import Path
from typing import Any

from immich_memories.db.network_guard import guard_sqlite_path

BUSY_TIMEOUT_MS = 30_000
_PRAGMAS = (
    f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA foreign_keys=ON",
)


def private_database_path(path: Path) -> Path:
    """Create at 0600 before SQLite opens it; keep existing sidecars private too."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Closing any separate descriptor for an existing database releases this
    # process's POSIX locks, including those held by live SQLite connections.
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        pass
    else:
        os.close(descriptor)
    path.chmod(0o600)
    for suffix in ("-journal", "-wal", "-shm"):
        sidecar = Path(str(path) + suffix)
        with contextlib.suppress(FileNotFoundError):
            sidecar.chmod(0o600)
    return path


def apply_pragmas(connection: Any) -> None:
    """Set the shared pragmas on a DB-API SQLite connection.

    WAL is asked for, not demanded: a read-only or overridden network file keeps the mode it
    has and still works.
    """
    cursor = connection.cursor()
    try:
        with contextlib.suppress(sqlite3.Error):
            cursor.execute("PRAGMA journal_mode=WAL")
        for pragma in _PRAGMAS:
            cursor.execute(pragma)
    finally:
        cursor.close()


def prepare_sqlite_file(path: Path, *, private: bool = True) -> Path:
    """Guard against network filesystems, then create the parent (and a 0600 file if private)."""
    path = Path(path)
    guard_sqlite_path(path)
    if private:
        return private_database_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def connect_sqlite(
    path: Path, *, private: bool = True, check_same_thread: bool = True, **kwargs: Any
) -> sqlite3.Connection:
    """Open `path` with the shared pragmas. The caller closes it.

    `private` creates the file at 0600 and keeps its sidecars there; a cache other tools read
    passes False. Extra keyword arguments go to `sqlite3.connect` (`detect_types`, ...).
    """
    target = prepare_sqlite_file(path, private=private)
    connection = sqlite3.connect(
        target,
        timeout=BUSY_TIMEOUT_MS / 1000,
        check_same_thread=check_same_thread,
        **kwargs,
    )
    try:
        apply_pragmas(connection)
    except BaseException:
        connection.close()
        raise
    return connection
