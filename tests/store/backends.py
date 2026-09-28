"""The backends the store suite runs on, and PostgreSQL schema housekeeping."""

from __future__ import annotations

import os

import pytest
import sqlalchemy as sa

from immich_memories.db.bootstrap import normalize_url

PG_ENV = "IMMICH_MEMORIES_TEST_DATABASE_URL"

requires_postgres = pytest.mark.skipif(not os.environ.get(PG_ENV), reason=f"{PG_ENV} is not set")

BACKENDS = [
    pytest.param("sqlite", id="sqlite"),
    pytest.param("postgresql", id="postgresql", marks=requires_postgres),
]


def pg_url() -> str:
    return normalize_url(os.environ[PG_ENV])


def drop_schema(url: str, schema: str) -> None:
    engine = sa.create_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(sa.schema.DropSchema(schema, cascade=True, if_exists=True))
    finally:
        engine.dispose()
