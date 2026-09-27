"""Named cross-process leases: a lock file on SQLite, a PostgreSQL advisory lock otherwise.

A lease guards work that must not run twice at once: a nightly automation pass, an assembly,
an editorial attempt. With a SQLite store every process shares one host, and the lease is the
`fcntl` lock file it always was. With a PostgreSQL store the processes may sit on different
machines, so the lease is a session-level `pg_try_advisory_lock` held on a connection kept
checked out for the lease's lifetime. Either way the operating system or the server drops it
when the holder dies: a closed file, a closed connection.

The advisory key is `(871_0002, hashtext(schema || ':' || name))`: its own class, apart from
the migration lock's `871_0001`, and the schema in the hash, so two stores sharing one
database never block each other.
"""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
from typing import TYPE_CHECKING

import sqlalchemy as sa

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection

    from immich_memories.db.store import Store

_LEASE_CLASS = 871_0002
_TAKE = sa.text("SELECT pg_advisory_lock(:lock_class, hashtext(:scope || ':' || :name))")
_TRY = sa.text("SELECT pg_try_advisory_lock(:lock_class, hashtext(:scope || ':' || :name))")
_DROP = sa.text("SELECT pg_advisory_unlock(:lock_class, hashtext(:scope || ':' || :name))")


class LeaseHeldError(RuntimeError):
    """Another process holds the lease."""


class Lease:
    """One named lease; `lock_path` is where the SQLite backend keeps its lock file.

    `store` picks the backend and defaults to the configured store.
    """

    def __init__(self, name: str, lock_path: Path, store: Store | None = None) -> None:
        self.name = name
        self.lock_path = Path(lock_path)
        self._store = store
        self._fd: int | None = None
        self._connection: Connection | None = None

    def _backend(self) -> Store | None:
        if self._store is None:
            from immich_memories.db.store import open_store

            self._store = open_store()
        return self._store if self._store.dialect_name == "postgresql" else None

    def _params(self, store: Store) -> dict[str, object]:
        return {"lock_class": _LEASE_CLASS, "scope": store.location.schema, "name": self.name}

    def acquire(self, *, wait: bool = False) -> None:
        """Take the lease, waiting for it when `wait`; otherwise refuse if it is held."""
        store = self._backend()
        if store is None:
            self._fd = _lock_file(self.lock_path, wait=wait)
            return
        connection = store.engine.connect()
        try:
            taken = connection.execute(_TAKE if wait else _TRY, self._params(store)).scalar()
            connection.commit()
        except BaseException:
            connection.invalidate()
            connection.close()
            raise
        if taken is False:
            connection.close()
            raise LeaseHeldError(f"lease {self.name!r} is held by another process")
        self._connection = connection

    def release(self) -> None:
        """Drop the lease. Safe to call when it was never taken."""
        if self._fd is not None:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
            self._fd = None
        if self._connection is not None:
            connection, self._connection = self._connection, None
            try:
                store = self._backend()
                assert store is not None
                connection.execute(_DROP, self._params(store))
                connection.commit()
            except BaseException:
                # A connection that may still hold the lock must never go back to the pool.
                connection.invalidate()
                raise
            finally:
                connection.close()

    def held_elsewhere(self) -> bool:
        """Whether some other holder has the lease right now (taken and dropped to find out).

        On SQLite the lock file must already exist, as it does for any lease once taken.
        """
        store = self._backend()
        if store is None:
            probe = os.open(self.lock_path, os.O_RDONLY)
            try:
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            finally:
                os.close(probe)
            return False
        try:
            self.acquire()
        except LeaseHeldError:
            return True
        self.release()
        return False

    def __enter__(self) -> Lease:
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


def _lock_file(path: Path, *, wait: bool) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX if wait else fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise LeaseHeldError(f"lease file {path} is held by another process") from None
    except BaseException:
        os.close(fd)
        raise
    return fd
