"""The opened store: one engine per location per process, migrated before first use."""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable, Iterator
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
FirstOpenHook = Callable[[Store], None]
_hooks: list[FirstOpenHook] = []
_hooked: set[tuple[tuple[str, str], FirstOpenHook]] = set()


def on_first_open(hook: FirstOpenHook) -> None:
    """Run `hook(store)` once per store per process, the first time `open_store` returns it.

    A hook runs after the migration lock is released and outside the open lock, so it may
    open the store again (it gets the cached one) and take its own locks. A store already
    open when the hook is registered gets it on its next `open_store`.
    """
    with _lock:
        if hook not in _hooks:
            _hooks.append(hook)


def open_store(config: Config | None = None, *, location: StoreLocation | None = None) -> Store:
    """The store for this location, opened and upgraded to head on first use in the process.

    The location comes from `resolve_location(config)` unless given. Later calls return the
    same `Store`, so there is one engine and one pool per location per process.
    """
    location = location or resolve_location(config)
    key = (location.url, effective_schema(location) or "")
    store = _open(location, key)
    with _lock:
        due = [hook for hook in _hooks if (key, hook) not in _hooked]
        _hooked.update((key, hook) for hook in due)
    for hook in due:
        hook(store)
    return store


def _open(location: StoreLocation, key: tuple[str, str]) -> Store:
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


def unmigrated_store(location: StoreLocation) -> Store:
    """A store on an engine of its own, neither migrated nor cached nor hooked.

    For the commands that report on or copy the database exactly as it is (`store status`,
    `store backup`). The caller disposes `store.engine`.
    """
    return Store(location=location, engine=create_store_engine(location))


def close_stores() -> None:
    """Dispose every engine this process opened; the next `open_store` starts over."""
    with _lock:
        stores = list(_stores.values())
        _stores.clear()
        _hooked.clear()
    for store in stores:
        store.engine.dispose()


def _forget_parent_stores() -> None:
    # A forked child must not reuse the parent's pooled connections; it reopens its own.
    global _lock
    _lock = threading.Lock()
    for store in _stores.values():
        store.engine.dispose(close=False)
    _stores.clear()
    _hooked.clear()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_forget_parent_stores)
