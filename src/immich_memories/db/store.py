"""The opened store: one engine per location per process, migrated before first use."""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy.engine import Connection, Engine

from immich_memories.db import migrate
from immich_memories.db.bootstrap import StoreLocation, resolve_location
from immich_memories.db.engine import SQLITE_BEGIN, create_store_engine, effective_schema

if TYPE_CHECKING:
    from immich_memories.config_loader import Config

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Store:
    """An open store. Repositories take one of these and do their work through it.

    `applied` holds the revisions this open migrated, empty when the database was current.
    """

    location: StoreLocation
    engine: Engine
    applied: tuple[str, ...] = ()

    @property
    def dialect_name(self) -> str:
        return self.engine.dialect.name

    @property
    def schema(self) -> str | None:
        """The PostgreSQL schema the tables live in; None on SQLite."""
        return effective_schema(self.location)

    @contextmanager
    def begin(self) -> Iterator[Connection]:
        """One short write transaction, committed on exit and rolled back on error.

        On SQLite it takes the write lock at BEGIN, so two writers queue on the busy timeout
        instead of one failing when it upgrades a read lock.
        """
        with self.engine.connect() as connection:
            connection.execution_options(**{SQLITE_BEGIN: "IMMEDIATE"})
            with connection.begin():
                yield connection

    def connect(self) -> Connection:
        """A connection for reads, or for a caller that manages its own transactions."""
        return self.engine.connect()


_stores: dict[tuple[str, str], Store] = {}  # (url, real schema)
_lock = threading.Lock()


def open_store(config: Config | None = None, *, location: StoreLocation | None = None) -> Store:
    """The store for this location, opened and upgraded to head on first use in the process.

    The location comes from `resolve_location(config)` unless given. Later calls return the
    same `Store`, so there is one engine and one pool per location per process.
    """
    location = location or resolve_location(config)
    key = (location.url, effective_schema(location) or "")
    with _lock:
        if (cached := _stores.get(key)) is not None:
            return cached
        engine = create_store_engine(location)
        try:
            applied = migrate.upgrade(Store(location=location, engine=engine))
        except BaseException:
            engine.dispose()
            raise
        if applied:
            logger.info("store %s upgraded: %s", location, ", ".join(applied))
        store = Store(location=location, engine=engine, applied=applied)
        _stores[key] = store
        return store


def close_stores() -> None:
    """Dispose every engine this process opened; the next `open_store` starts over."""
    with _lock:
        stores = list(_stores.values())
        _stores.clear()
    for store in stores:
        store.engine.dispose()


def _forget_parent_stores() -> None:
    # A forked child must not reuse the parent's pooled connections; it reopens its own.
    global _lock
    _lock = threading.Lock()
    for store in _stores.values():
        store.engine.dispose(close=False)
    _stores.clear()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_forget_parent_stores)
