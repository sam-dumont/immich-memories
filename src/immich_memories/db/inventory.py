"""What a store holds, table by table: row counts and content digests both backends agree on.

A digest is order-free (the sum of one SHA-256 per row, modulo 2**256), because the two
backends sort text differently, and it reads every value in a backend-neutral form: JSON with
sorted keys, datetimes as ISO text, bytes as hex. Two stores holding the same rows digest the
same whichever backend each sits on.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import date, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from immich_memories.db.migrate import VERSION_TABLE
from immich_memories.db.tables import metadata

_MODULUS = 2**256
_BATCH = 5000


def store_tables() -> list[sa.Table]:
    """Every store table, parents before children."""
    return list(metadata.sorted_tables)


def row_counts(connection: Connection) -> dict[str, int]:
    """Rows per store table."""
    return {table.name: _count(connection, table) for table in store_tables()}


def present_counts(connection: Connection, schema: str | None) -> dict[str, int]:
    """Rows per store table that exists; a database older than head lacks some."""
    present = set(sa.inspect(connection).get_table_names(schema=schema))
    return {
        table.name: _count(connection, table) for table in store_tables() if table.name in present
    }


def recorded_revisions(connection: Connection, schema: str | None) -> tuple[str, ...]:
    """The revisions the database says it is at, read without Alembic; empty before any."""
    if not sa.inspect(connection).has_table(VERSION_TABLE, schema=schema):
        return ()
    version = sa.table(VERSION_TABLE, sa.column("version_num"), schema=schema)
    return tuple(sorted(connection.execute(sa.select(version.c.version_num)).scalars()))


def _count(connection: Connection, table: sa.Table) -> int:
    return int(connection.execute(sa.select(sa.func.count()).select_from(table)).scalar() or 0)


def table_digest(connection: Connection, table: sa.Table) -> tuple[int, str]:
    """(rows, digest) of one table's content."""
    total = 0
    rows = 0
    result = connection.execution_options(stream_results=True).execute(sa.select(table))
    for batch in result.partitions(_BATCH):
        for row in batch:
            total = (total + _row_hash(table, row._mapping)) % _MODULUS
            rows += 1
    return rows, f"{total:064x}"


def digests(connection: Connection) -> dict[str, tuple[int, str]]:
    """(rows, digest) for every store table."""
    return {table.name: table_digest(connection, table) for table in store_tables()}


def _row_hash(table: sa.Table, row: Any) -> int:
    values = [_neutral(row[column.name]) for column in table.columns]
    text = json.dumps(values, sort_keys=True, separators=(",", ":"))
    return int.from_bytes(hashlib.sha256(text.encode()).digest(), "big")


def _neutral(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, bytes | memoryview):
        return bytes(value).hex()
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, dict):
        return {str(key): _neutral(item) for key, item in value.items()}
    if isinstance(value, Iterable) and not isinstance(value, str):
        return [_neutral(item) for item in value]
    return value
