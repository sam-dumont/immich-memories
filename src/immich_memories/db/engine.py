"""Build the SQLAlchemy engine for a store location, the same way on every call.

SQLite gets the shared pragmas on every pooled connection, a private file, and explicit
`BEGIN`s: pysqlite's own transaction handling starts transactions late and cannot take a write
lock up front, which is what a short write transaction needs to never deadlock on upgrade.
PostgreSQL gets psycopg 3 and a small pre-pinged pool.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Connection, Engine

from immich_memories.db.bootstrap import StoreLocation
from immich_memories.db.metadata import SCHEMA
from immich_memories.db.sqlite_files import BUSY_TIMEOUT_MS, apply_pragmas, prepare_sqlite_file

# The execution option `Store.begin()` sets to take SQLite's write lock at BEGIN.
SQLITE_BEGIN = "sqlite_begin"
_BEGIN_MODES = {"DEFERRED", "IMMEDIATE", "EXCLUSIVE"}


def effective_schema(location: StoreLocation) -> str | None:
    """The schema the tables really live in: the configured one, or none on SQLite."""
    return None if location.dialect_name == "sqlite" else location.schema


def create_store_engine(location: StoreLocation) -> Engine:
    """A new engine for `location`. Callers wanting the shared one use `open_store`."""
    translate = {"schema_translate_map": {SCHEMA: effective_schema(location)}}
    if location.dialect_name == "sqlite":
        return _sqlite_engine(location, translate)
    return create_engine(
        location.sa_url,
        pool_size=5,
        pool_pre_ping=True,
        execution_options=translate,
    )


def _sqlite_engine(location: StoreLocation, execution_options: dict[str, Any]) -> Engine:
    path = location.sqlite_path
    if path is not None:
        prepare_sqlite_file(path, private=True)
    engine = create_engine(
        location.sa_url,
        # isolation_level=None: autocommit at the driver; `_on_sqlite_begin` emits every BEGIN.
        connect_args={"timeout": BUSY_TIMEOUT_MS / 1000, "isolation_level": None},
        execution_options=execution_options,
    )
    event.listen(engine, "connect", _on_sqlite_connect)
    event.listen(engine, "begin", _on_sqlite_begin)
    return engine


def _on_sqlite_connect(dbapi_connection: Any, _record: Any) -> None:
    apply_pragmas(dbapi_connection)


def _on_sqlite_begin(connection: Connection) -> None:
    mode = str(connection.get_execution_options().get(SQLITE_BEGIN, "DEFERRED")).upper()
    if mode not in _BEGIN_MODES:
        raise ValueError(f"unknown SQLite BEGIN mode {mode!r}")
    connection.exec_driver_sql(f"BEGIN {mode}")
