"""Run every store test on SQLite, and on PostgreSQL when a server is named.

`IMMICH_MEMORIES_TEST_DATABASE_URL` points at a PostgreSQL database the suite may create
schemas in. Each test gets its own random schema, dropped afterwards, so the tests stay
isolated and every one of them exercises a store that shares its database with others.
Without the variable the PostgreSQL cases skip; `make test-store` starts a server for them.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest

from immich_memories.db import Store, StoreLocation, close_stores, open_store

from .backends import BACKENDS, drop_schema, pg_url


@pytest.fixture(params=BACKENDS)
def location(request, tmp_path) -> Iterator[StoreLocation]:
    """A fresh, not yet opened store location on each backend."""
    if request.param == "sqlite":
        yield StoreLocation(url=f"sqlite:///{tmp_path / 'store.db'}")
        close_stores()
        return
    schema = f"test_{uuid.uuid4().hex[:12]}"
    url = pg_url()
    yield StoreLocation(url=url, schema=schema)
    close_stores()
    drop_schema(url, schema)


@pytest.fixture
def store(location: StoreLocation) -> Store:
    """An opened, migrated store on each backend."""
    return open_store(location=location)
