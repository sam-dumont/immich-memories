"""`store copy`: every table into another store, SQLite to PostgreSQL and back, identical."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from click.testing import CliRunner

from immich_memories.automation.state_store import AutomationStateStore
from immich_memories.config_loader import Config, set_config
from immich_memories.db import StoreLocation, close_stores, open_store
from immich_memories.db.copy import TargetNotEmptyError, copy_store
from immich_memories.db.inventory import digests

from .backends import drop_schema, pg_url, requires_postgres
from .legacy_home import fill_every_table, write_legacy_home


@pytest.fixture
def home(tmp_path) -> Iterator[Path]:
    config = Config()
    config.cache.database = "~/.immich-memories/cache.db"
    config.cache.directory = "~/.immich-memories/cache"
    set_config(config)
    yield write_legacy_home(tmp_path / "home")
    set_config(None)


@pytest.fixture
def pg_schema() -> Iterator[StoreLocation]:
    schema = f"test_{uuid.uuid4().hex[:12]}"
    yield StoreLocation(url=pg_url(), schema=schema)
    close_stores()
    drop_schema(pg_url(), schema)


def _digests(store):
    with store.connect() as connection:
        return digests(connection)


@requires_postgres
def test_sqlite_to_postgresql_and_back_is_identical(tmp_path, home, pg_schema):
    source = open_store(location=StoreLocation(url=f"sqlite:///{tmp_path / 'source.db'}"))
    fill_every_table(source, home)
    middle = open_store(location=pg_schema)
    back = open_store(location=StoreLocation(url=f"sqlite:///{tmp_path / 'back.db'}"))

    there = copy_store(source, middle)
    again = copy_store(middle, back)

    assert there.mismatched == again.mismatched == ()
    assert _digests(source) == _digests(middle) == _digests(back)
    assert all(there.copied.values())
    # The copy wrote explicit ids: the next one the database hands out must not collide.
    AutomationStateStore(middle).start_attempt("after the copy")


def test_a_target_holding_rows_is_refused_unless_forced(location, tmp_path, home):
    source = open_store(location=StoreLocation(url=f"sqlite:///{tmp_path / 'source.db'}"))
    fill_every_table(source, home)
    target = open_store(location=location)
    AutomationStateStore(target).start_attempt("already here")

    with pytest.raises(TargetNotEmptyError, match="automation_attempts"):
        copy_store(source, target)
    report = copy_store(source, target, force=True)

    assert report.mismatched == ()
    assert _digests(target) == _digests(source)


def test_the_cli_copies_into_another_url(tmp_path, home, monkeypatch):
    from immich_memories.cli import main

    source_path = tmp_path / "source.db"
    fill_every_table(open_store(location=StoreLocation(url=f"sqlite:///{source_path}")), home)
    monkeypatch.setenv("IMMICH_MEMORIES_DATABASE_URL", f"sqlite:///{source_path}")
    target = tmp_path / "target.db"

    result = CliRunner().invoke(main, ["store", "copy", "--to", f"sqlite:///{target}"])

    assert result.exit_code == 0, result.output
    assert "every table matches" in result.output
    refused = CliRunner().invoke(main, ["store", "copy", "--to", f"sqlite:///{target}"])
    assert refused.exit_code == 1
    assert "--force" in refused.output
