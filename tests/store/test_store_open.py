"""Opening the store: one engine per location, safe SQLite settings, concurrent starts."""

from __future__ import annotations

import multiprocessing
import stat
from datetime import datetime

import sqlalchemy as sa

from immich_memories.db import StoreLocation, close_stores, current_revisions, heads, open_store
from immich_memories.db.tables import store_meta


def test_the_same_location_shares_one_store(location):
    assert open_store(location=location) is open_store(location=location)


def test_a_sqlite_store_runs_with_the_shared_pragmas_in_a_private_file(tmp_path):
    path = tmp_path / "home" / "store.db"
    store = open_store(location=StoreLocation(url=f"sqlite:///{path}"))
    try:
        with store.connect() as connection:
            values = [
                connection.exec_driver_sql(f"PRAGMA {name}").scalar()
                for name in ("journal_mode", "busy_timeout", "synchronous", "foreign_keys")
            ]
        assert values == ["wal", 30000, 1, 1]
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert store.schema is None
    finally:
        close_stores()


def test_a_write_commits_and_a_failed_one_rolls_back(store):
    row = {"key": "k", "value": {"n": 1}, "updated_at": datetime(2026, 9, 27, 12)}
    with store.begin() as connection:
        connection.execute(store_meta.insert(), row)
    try:
        with store.begin() as connection:
            connection.execute(store_meta.update().values(value={"n": 2}))
            raise RuntimeError("abandon")
    except RuntimeError:
        pass

    with store.connect() as connection:
        assert connection.execute(sa.select(store_meta.c.value)).scalar_one() == {"n": 1}


def _open_in_child(url: str, schema: str) -> tuple[str, ...]:
    return open_store(location=StoreLocation(url=url, schema=schema)).applied


def test_concurrent_first_starts_migrate_exactly_once(location):
    context = multiprocessing.get_context("spawn")
    with context.Pool(4) as pool:
        applied = pool.starmap(_open_in_child, [(location.url, location.schema)] * 4)

    assert sorted(bool(revisions) for revisions in applied) == [False, False, False, True]
    assert set(current_revisions(open_store(location=location))) == set(heads())
