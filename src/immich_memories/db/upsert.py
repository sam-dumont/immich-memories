"""Insert-or-update in one statement, on either backend."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from sqlalchemy import Table
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.engine import Connection


def upsert(
    connection: Connection,
    table: Table,
    rows: Iterable[Mapping[str, Any]],
    keys: Sequence[str],
    update: Sequence[str] | None = None,
) -> None:
    """Insert `rows`; where `keys` already exist, overwrite the `update` columns.

    `update=None` overwrites every non-key column; an empty `update` keeps the existing row
    untouched (`ON CONFLICT DO NOTHING`). `keys` must be a primary key or a unique constraint.
    Every row carries the same columns.
    """
    batch = [dict(row) for row in rows]
    if not batch:
        return
    dialect = postgresql if connection.dialect.name == "postgresql" else sqlite
    statement = dialect.insert(table)
    columns = [c.name for c in table.columns if c.name not in keys] if update is None else update
    if columns:
        statement = statement.on_conflict_do_update(
            index_elements=list(keys),
            set_={name: statement.excluded[name] for name in columns},
        )
    else:
        statement = statement.on_conflict_do_nothing(index_elements=list(keys))
    connection.execute(statement, batch)
