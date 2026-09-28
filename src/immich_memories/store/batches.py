"""Id lists in a WHERE clause: as few statements as the backend allows, never past its limits.

PostgreSQL takes a whole list as one array parameter (`= ANY(:ids)`), which it plans in one
pass however long the list is; an `IN` of twenty thousand bound values costs it several
times the query itself. SQLite has no arrays, so there the list is an `IN` in slices under
its bind limit.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from typing import TYPE_CHECKING, Any, TypeVar

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Connection

from immich_memories.db import upsert

if TYPE_CHECKING:
    from immich_memories.db import Store

T = TypeVar("T")

# SQLite builds before 3.32 bind at most 999 variables; psycopg binds at most 65535. Both
# leave room for the other parameters of the statement.
_BIND_LIMIT = {"sqlite": 900, "postgresql": 30_000}


def in_chunks(
    connection: Connection, values: Sequence[T], per_row: int = 1
) -> Iterator[Sequence[T]]:
    """`values` in order, in slices that fit one statement.

    With `per_row=1` the slice is meant for `id_in`, which PostgreSQL binds as one array, so
    there it is the whole list. A tuple `IN` binds `per_row` values per row on every backend.
    """
    backend = connection.dialect.name
    if backend == "postgresql" and per_row == 1:
        size = max(1, len(values))
    else:
        size = max(1, _BIND_LIMIT.get(backend, 900) // per_row)
    for start in range(0, len(values), size):
        yield values[start : start + size]


def id_in(connection: Connection, column: Any, values: Sequence[str]) -> sa.ColumnElement[bool]:
    """`column` is one of `values`: an array parameter on PostgreSQL, an `IN` list elsewhere."""
    if connection.dialect.name == "postgresql":
        return column == sa.any_(sa.bindparam(None, list(values), type_=postgresql.ARRAY(sa.Text)))
    return column.in_(values)


def upsert_rows(
    connection: Connection,
    table: sa.Table,
    rows: Sequence[Mapping[str, Any]],
    keys: Sequence[str],
    update: Sequence[str] | None = None,
) -> None:
    """`db.upsert` for a batch that may name a key twice: the last row for a key wins.

    PostgreSQL refuses a key twice in one batch, which row-by-row SQLite never did. The
    rows go out as one executemany, which psycopg pipelines into one round trip; a
    multi-row VALUES statement measured slower there, because psycopg re-parses a long
    statement on every call.
    """
    latest = list({tuple(row[key] for key in keys): row for row in rows}.values())
    if latest:
        upsert(connection, table, latest, keys, update)


def bank_rows(
    store: Store,
    table: sa.Table,
    rows: Sequence[Mapping[str, Any]],
    keys: Sequence[str],
    update: Sequence[str] | None = None,
) -> None:
    """One batch of rows in one short transaction: the unit a crash can cost."""
    if rows:
        with store.begin() as connection:
            upsert_rows(connection, table, rows, keys, update)


def insert_rows(connection: Connection, table: sa.Table, rows: Sequence[Mapping[str, Any]]) -> None:
    """Plain inserts as one executemany; a conflict raises."""
    if rows:
        connection.execute(sa.insert(table), list(rows))
