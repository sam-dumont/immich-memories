"""Seed and read the store's annotation tables in tests, by column name.

Replaces the raw `annotations.sqlite` fixtures: a row is a mapping, a column it leaves out
is NULL, and an ISO timestamp is converted the way the repositories convert one.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import sqlalchemy as sa
from sqlalchemy import DateTime, Table

from immich_memories.db import Store, now_db, open_store, to_db
from immich_memories.db import tables as store_tables


def annotation_store() -> Store:
    """The store this test's environment names (a fresh file per test, see conftest)."""
    return open_store()


def table_named(name: str) -> Table:
    return getattr(store_tables, name)


def add_rows(store: Store, table: str | Table, *rows: Mapping[str, Any]) -> None:
    """Insert `rows` as given; a column a row leaves out is NULL.

    A required timestamp left out is now, and a face box without an `ordinal` takes the
    next one of its picture, so a test states only what it is about.
    """
    target = table_named(table) if isinstance(table, str) else table
    ordinals: dict[str, int] = {}
    prepared = []
    for row in rows:
        values = {
            column.name: _stored(column, row[column.name])
            for column in target.columns
            if column.name in row
        }
        for column in target.columns:
            if column.name not in values and not column.nullable:
                if isinstance(column.type, DateTime):
                    values[column.name] = now_db()
                elif column.name == "ordinal":
                    values["ordinal"] = ordinals.get(values["asset_id"], 0)
        if "ordinal" in values:
            ordinals[values["asset_id"]] = values["ordinal"] + 1
        prepared.append(values)
    with store.begin() as connection:
        for row in prepared:
            connection.execute(sa.insert(target).values(row))


def read_rows(store: Store, table: str | Table) -> list[dict[str, Any]]:
    """Every row of `table`, as plain dicts in primary-key order."""
    target = table_named(table) if isinstance(table, str) else table
    with store.connect() as connection:
        query = sa.select(target).order_by(*target.primary_key.columns)
        return [dict(row._mapping) for row in connection.execute(query)]


def count_rows(store: Store, table: str | Table) -> int:
    return len(read_rows(store, table))


def _stored(column: sa.Column, value: Any) -> Any:
    if isinstance(column.type, DateTime) and isinstance(value, str):
        return to_db(value)
    return value
