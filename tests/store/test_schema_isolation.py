"""A PostgreSQL store shares its database: it touches its own schema and nothing else."""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from immich_memories.db import (
    StoreLocation,
    close_stores,
    downgrade,
    open_store,
    pending_changes,
)
from immich_memories.db.tables import metadata

from .backends import drop_schema, pg_url, requires_postgres

pytestmark = requires_postgres


def _their_tables(public_table: str, other: str) -> list[sa.Table]:
    """One table in `public`, then a namesake of every store table and of the version table."""
    theirs = sa.MetaData()
    names = [table.name for table in metadata.sorted_tables] + ["alembic_version"]
    return [
        sa.Table(
            public_table, theirs, sa.Column("id", sa.Integer, primary_key=True), schema="public"
        ),
        *(
            sa.Table(name, theirs, sa.Column("id", sa.Integer, primary_key=True), schema=other)
            for name in names
        ),
    ]


@pytest.fixture
def neighbours():
    """Someone else's tables, each holding a row: one in `public`, and ours' namesakes in
    another schema."""
    url = pg_url()
    tag = uuid.uuid4().hex[:8]
    other = f"immich_{tag}"
    tables = _their_tables(f"assets_{tag}", other)
    engine = sa.create_engine(url)
    with engine.begin() as connection:
        connection.execute(sa.schema.CreateSchema(other))
        tables[0].metadata.create_all(connection)
        for table in tables:
            connection.execute(table.insert(), {"id": 1})
    yield engine, tables
    tables[0].drop(engine, checkfirst=True)
    engine.dispose()
    drop_schema(url, other)


def _snapshot(engine, tables):
    other = tables[1].schema
    with engine.connect() as connection:
        inspector = sa.inspect(connection)
        return (
            sorted(inspector.get_table_names(schema=other)),
            {
                (table.schema, table.name): (
                    [c["name"] for c in inspector.get_columns(table.name, schema=table.schema)],
                    connection.execute(sa.select(table)).all(),
                )
                for table in tables
            },
        )


def test_migrating_up_and_down_leaves_every_other_schema_alone(neighbours):
    engine, tables = neighbours
    before = _snapshot(engine, tables)
    schema = f"test_{uuid.uuid4().hex[:12]}"
    try:
        store = open_store(location=StoreLocation(url=pg_url(), schema=schema))
        with store.connect() as connection:
            ours = set(sa.inspect(connection).get_table_names(schema=schema))

        assert ours == {table.name for table in metadata.sorted_tables} | {"alembic_version"}
        assert pending_changes(store) == []
        assert _snapshot(engine, tables) == before

        downgrade(store, "base")

        assert _snapshot(engine, tables) == before
    finally:
        close_stores()
        drop_schema(pg_url(), schema)


def test_a_schema_name_is_quoted_never_interpolated(neighbours):
    engine, tables = neighbours
    schema = f'odd"; DROP TABLE public."{tables[0].name}"; --'
    try:
        open_store(location=StoreLocation(url=pg_url(), schema=schema))
        with engine.connect() as connection:
            assert connection.execute(sa.select(tables[0].c.id)).all() == [(1,)]
            assert schema in sa.inspect(connection).get_schema_names()
    finally:
        close_stores()
        drop_schema(pg_url(), schema)
