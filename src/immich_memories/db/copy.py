"""Copy every store table into another store: SQLite to PostgreSQL, and back.

The target is migrated to head first, so both sides have the same tables. Rows move in
batches, parents before children, in one transaction on the target. Afterwards each table's
row count and content digest must match the source's, or the copy is reported as failed.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from immich_memories.db.inventory import digests, row_counts, store_tables
from immich_memories.db.store import Store

_BATCH = 5000


class TargetNotEmptyError(RuntimeError):
    """The target store already holds rows and the copy was not forced."""


@dataclass(frozen=True)
class CopyReport:
    """Rows copied per table, and every table whose count or digest did not match."""

    copied: dict[str, int]
    mismatched: tuple[str, ...]


def copy_store(source: Store, target: Store, *, force: bool = False) -> CopyReport:
    """Copy `source` into `target`, then compare every table.

    A target holding any row is refused unless `force`, which empties it first. Both stores
    must already be open (and so migrated to head).
    """
    with target.connect() as connection:
        held = {name: count for name, count in row_counts(connection).items() if count}
    if held and not force:
        listing = ", ".join(f"{name} ({count})" for name, count in sorted(held.items()))
        raise TargetNotEmptyError(f"the target store already holds rows: {listing}")
    copied: dict[str, int] = {}
    with source.connect() as reader, target.begin() as writer:
        for table in reversed(store_tables()):
            writer.execute(sa.delete(table))
        for table in store_tables():
            copied[table.name] = _copy_table(reader, writer, table)
        if target.dialect_name == "postgresql":
            _advance_sequences(writer, target.schema)
    with source.connect() as before, target.connect() as after:
        theirs, ours = digests(before), digests(after)
    mismatched = tuple(name for name in theirs if theirs[name] != ours.get(name))
    return CopyReport(copied=copied, mismatched=mismatched)


def _copy_table(reader: Connection, writer: Connection, table: sa.Table) -> int:
    count = 0
    result = reader.execution_options(stream_results=True).execute(sa.select(table))
    for batch in result.mappings().partitions(_BATCH):
        writer.execute(sa.insert(table), [dict(row) for row in batch])
        count += len(batch)
    return count


def _advance_sequences(writer: Connection, schema: str | None) -> None:
    """Point every serial key's sequence past the ids the copy wrote explicitly."""
    preparer = writer.dialect.identifier_preparer
    for table in store_tables():
        keys = list(table.primary_key.columns)
        if len(keys) != 1 or not isinstance(keys[0].type, sa.Integer):
            continue
        qualified = f"{preparer.quote_schema(schema or 'public')}.{preparer.quote(table.name)}"
        sequence = writer.execute(
            sa.select(sa.func.pg_get_serial_sequence(qualified, keys[0].name))
        ).scalar()
        if sequence is None:
            continue
        highest = writer.execute(sa.select(sa.func.max(keys[0]))).scalar()
        writer.execute(sa.select(sa.func.setval(sequence, highest or 1, highest is not None)))
