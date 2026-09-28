"""`store backup` / `store restore`: the drill on both backends, and what a restore refuses."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from click.testing import CliRunner
from sqlalchemy.engine import make_url

from immich_memories.automation.state_store import AutomationStateStore
from immich_memories.config_loader import Config, set_config
from immich_memories.db import StoreLocation, close_stores, heads, open_store
from immich_memories.db.backup import BackupError, backup_store, manifest_path, restore_store
from immich_memories.db.inventory import digests

from .backends import drop_schema, pg_url, requires_postgres
from .legacy_home import fill_every_table, write_legacy_home


@pytest.fixture
def filled(location, tmp_path) -> Iterator:
    config = Config()
    config.cache.database = "~/.immich-memories/cache.db"
    config.cache.directory = "~/.immich-memories/cache"
    set_config(config)
    store = open_store(location=location)
    fill_every_table(store, write_legacy_home(tmp_path / "home"))
    yield store
    set_config(None)


def _digests(store):
    with store.connect() as connection:
        return digests(connection)


@pytest.fixture
def scratch(location, tmp_path) -> Iterator[StoreLocation]:
    """An empty target for the drill: another SQLite file, or another PostgreSQL database."""
    if location.dialect_name == "sqlite":
        yield StoreLocation(url=f"sqlite:///{tmp_path / 'scratch' / 'store.db'}")
        return
    name = f"scratch_{uuid.uuid4().hex[:12]}"
    admin = sa.create_engine(pg_url(), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(sa.text(f'CREATE DATABASE "{name}"'))
    yield StoreLocation(
        url=make_url(location.url).set(database=name).render_as_string(False),
        schema=location.schema,
    )
    close_stores()
    with admin.connect() as connection:
        connection.execute(sa.text(f'DROP DATABASE "{name}" WITH (FORCE)'))
    admin.dispose()


def test_the_restore_drill_brings_back_every_table(filled, location, scratch, tmp_path):
    before = _digests(filled)
    backup = tmp_path / "backups" / "store.backup"

    manifest = backup_store(filled, backup)
    restore_store(scratch, backup)
    restored = open_store(location=scratch)

    assert _digests(restored) == before
    assert manifest.backend == location.dialect_name
    assert set(manifest.revisions) == set(heads())
    assert manifest.counts == {name: rows for name, (rows, _) in before.items()}
    written = json.loads(manifest_path(backup).read_text())
    assert set(written) == {"app_version", "revisions", "backend", "schema", "counts", "created_at"}


@requires_postgres
def test_a_postgresql_backup_restores_under_another_schema_name(tmp_path):
    first = StoreLocation(url=pg_url(), schema=f"test_{uuid.uuid4().hex[:12]}")
    second = StoreLocation(url=pg_url(), schema=f"test_{uuid.uuid4().hex[:12]}")
    AutomationStateStore(open_store(location=first)).start_attempt("in the first schema")
    before = _digests(open_store(location=first))
    backup = tmp_path / "store.dump"
    backup_store(open_store(location=first), backup)
    close_stores()
    drop_schema(pg_url(), first.schema)
    try:
        restore_store(second, backup)

        assert _digests(open_store(location=second)) == before
    finally:
        close_stores()
        drop_schema(pg_url(), second.schema)


def test_a_restore_over_the_store_itself_needs_force(filled, location, tmp_path):
    before = _digests(filled)
    backup = tmp_path / "store.backup"
    backup_store(filled, backup)
    AutomationStateStore(filled).start_attempt("after the backup")

    with pytest.raises(BackupError, match="--force"):
        restore_store(location, backup)
    restore_store(location, backup, force=True)

    assert _digests(open_store(location=location)) == before


def test_a_backup_never_overwrites_a_file(filled, tmp_path):
    backup = tmp_path / "store.backup"
    backup.write_text("keep me")

    with pytest.raises(BackupError, match="already exists"):
        backup_store(filled, backup)
    assert backup.read_text() == "keep me"


def test_a_backup_restores_only_into_its_own_backend(filled, location, tmp_path):
    backup = tmp_path / "store.backup"
    backup_store(filled, backup)
    # The backend is checked before anything connects, so the other URL need not answer.
    other = (
        StoreLocation(url="postgresql+psycopg://nobody@127.0.0.1:1/none", schema="unused")
        if location.dialect_name == "sqlite"
        else StoreLocation(url=f"sqlite:///{tmp_path / 'x.db'}")
    )

    with pytest.raises(BackupError, match="store copy"):
        restore_store(other, backup)


@requires_postgres
def test_without_pg_dump_the_error_says_what_to_install(monkeypatch, tmp_path):
    schema = f"test_{uuid.uuid4().hex[:12]}"
    store = open_store(location=StoreLocation(url=pg_url(), schema=schema))
    monkeypatch.setenv("PATH", str(tmp_path))
    try:
        with pytest.raises(BackupError, match="pg_dump was not found on PATH.*postgresql-client"):
            backup_store(store, tmp_path / "store.dump")
    finally:
        close_stores()
        drop_schema(pg_url(), schema)


def test_the_cli_backs_up_reports_and_restores(tmp_path, monkeypatch):
    from immich_memories.cli import main

    path = tmp_path / "store.db"
    monkeypatch.setenv("IMMICH_MEMORIES_DATABASE_URL", f"sqlite:///{path}")
    AutomationStateStore(open_store(location=StoreLocation(url=f"sqlite:///{path}"))).start_attempt(
        "before the backup"
    )
    runner = CliRunner()
    backup = tmp_path / "store.backup"

    made = runner.invoke(main, ["store", "backup", "--to", str(backup)])
    status = runner.invoke(main, ["store", "status"])
    refused = runner.invoke(main, ["store", "restore", "--from", str(backup)])
    forced = runner.invoke(main, ["store", "restore", "--from", str(backup), "--force"])

    assert made.exit_code == 0, made.output
    assert manifest_path(backup).exists()
    assert status.exit_code == 0, status.output
    assert "Backend:   sqlite" in status.output
    assert "(at head)" in status.output
    assert "automation_attempts" in status.output
    assert refused.exit_code == 1
    assert forced.exit_code == 0, forced.output
