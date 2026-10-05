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


def _truncate(backup, tmp_path, name="truncated.backup"):
    """A copy of `backup`, cut in half, with the same (valid) manifest beside it."""
    corrupt = tmp_path / name
    data = backup.read_bytes()
    corrupt.write_bytes(data[: len(data) // 2])
    manifest_path(corrupt).write_text(manifest_path(backup).read_text())
    return corrupt


def test_a_truncated_backup_with_force_leaves_the_populated_store_untouched(
    filled, location, tmp_path
):
    before = _digests(filled)
    backup = tmp_path / "store.backup"
    backup_store(filled, backup)
    close_stores()
    # Captured after the backup's own VACUUM INTO (which can checkpoint the source file) and
    # after closing every engine, so the only thing that could still move these bytes is restore.
    before_bytes = location.sqlite_path.read_bytes() if location.sqlite_path else None
    corrupt = _truncate(backup, tmp_path)

    with pytest.raises(BackupError):
        restore_store(location, corrupt, force=True)

    if before_bytes is not None:
        assert location.sqlite_path.read_bytes() == before_bytes
    assert _digests(open_store(location=location)) == before


def test_a_logically_corrupt_backup_fails_integrity_check_cleanly(filled, location, tmp_path):
    """`PRAGMA integrity_check` returns a bad row instead of raising; that path needs its own
    corruption, distinct from `_truncate`'s, which breaks the file too early to reach it."""
    if location.dialect_name != "sqlite":
        pytest.skip("integrity_check is a SQLite-only validation step")
    before = _digests(filled)
    backup = tmp_path / "store.backup"
    backup_store(filled, backup)
    close_stores()
    before_bytes = location.sqlite_path.read_bytes()
    corrupt = tmp_path / "logically_corrupt.backup"
    data = bytearray(backup.read_bytes())
    # Zero out the middle third, well past the 100-byte header: the file still opens (its
    # header is untouched), but enough B-tree pages disagree with their neighbours that
    # integrity_check reports it instead of sqlite3 refusing to open the file outright.
    start, end = len(data) // 3, 2 * len(data) // 3
    data[start:end] = b"\x00" * (end - start)
    corrupt.write_bytes(bytes(data))
    manifest_path(corrupt).write_text(manifest_path(backup).read_text())

    with pytest.raises(BackupError, match="not a valid SQLite database"):
        restore_store(location, corrupt, force=True)

    assert location.sqlite_path.read_bytes() == before_bytes
    assert _digests(open_store(location=location)) == before


def test_a_manifest_mismatch_after_a_good_swap_rolls_back_the_old_file(filled, location, tmp_path):
    """The staged file itself is fine and swaps in cleanly; only the post-swap row-count check
    against the manifest fails. The swap must still undo itself, not just report the error."""
    before = _digests(filled)
    backup = tmp_path / "store.backup"
    backup_store(filled, backup)
    close_stores()
    before_bytes = location.sqlite_path.read_bytes() if location.sqlite_path else None
    tampered = json.loads(manifest_path(backup).read_text())
    tampered["counts"] = {name: count + 1 for name, count in tampered["counts"].items()}
    manifest_path(backup).write_text(json.dumps(tampered))

    with pytest.raises(BackupError, match="does not match its manifest"):
        restore_store(location, backup, force=True)

    if before_bytes is not None:
        assert location.sqlite_path.read_bytes() == before_bytes
    assert _digests(open_store(location=location)) == before


def test_the_cli_reports_a_truncated_backup_cleanly_and_exits_non_zero(filled, location, tmp_path):
    from immich_memories.cli import main

    if location.dialect_name != "sqlite":
        pytest.skip("the CLI drill below only wires up a SQLite URL")
    before = _digests(filled)
    backup = tmp_path / "store.backup"
    backup_store(filled, backup)
    close_stores()
    corrupt = _truncate(backup, tmp_path)
    runner = CliRunner(env={"IMMICH_MEMORIES_DATABASE_URL": location.url})

    result = runner.invoke(main, ["store", "restore", "--from", str(corrupt), "--force"])

    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert _digests(open_store(location=location)) == before


def test_a_truncated_backup_into_an_empty_target_is_not_created_or_left_corrupt(
    filled, scratch, tmp_path
):
    backup = tmp_path / "store.backup"
    backup_store(filled, backup)
    corrupt = _truncate(backup, tmp_path)

    with pytest.raises(BackupError):
        restore_store(scratch, corrupt)

    if scratch.sqlite_path is not None:
        assert not scratch.sqlite_path.exists()
    else:
        engine = sa.create_engine(scratch.url)
        try:
            with engine.connect() as connection:
                assert not sa.inspect(connection).has_schema(scratch.schema)
        finally:
            engine.dispose()


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


@requires_postgres
def test_mode_four_restore_checks_database_create_before_dropping_the_store(tmp_path):
    from immich_memories.settings_store import SettingsStore

    role = f"restore_{uuid.uuid4().hex[:12]}"
    schema = role
    admin = sa.create_engine(pg_url(), isolation_level="AUTOCOMMIT")
    database = make_url(pg_url()).database
    password = "synthetic-restore-role-password"  # noqa: S105 — throwaway database only
    location = StoreLocation(
        url=make_url(pg_url()).set(username=role, password=password).render_as_string(False),
        schema=schema,
    )
    quote = admin.dialect.identifier_preparer.quote
    try:
        with admin.connect() as connection:
            connection.execute(sa.text(f"CREATE ROLE {quote(role)} LOGIN PASSWORD '{password}'"))
            connection.execute(
                sa.text(f"CREATE SCHEMA {quote(schema)} AUTHORIZATION {quote(role)}")
            )
        store = open_store(location=location)
        SettingsStore(store, None).save({"output.resolution": "720p"})
        before = _digests(store)
        backup = tmp_path / "restricted.dump"
        backup_store(store, backup)
        close_stores()

        with pytest.raises(BackupError, match="CREATE on database"):
            restore_store(location, backup, force=True)
        assert _digests(open_store(location=location)) == before
        close_stores()

        with admin.connect() as connection:
            connection.execute(
                sa.text(f"GRANT CREATE ON DATABASE {quote(database)} TO {quote(role)}")
            )
        restore_store(location, backup, force=True)
        assert _digests(open_store(location=location)) == before
    finally:
        close_stores()
        with admin.connect() as connection:
            connection.execute(sa.schema.DropSchema(schema, cascade=True, if_exists=True))
            connection.execute(sa.text(f"DROP OWNED BY {quote(role)}"))
            connection.execute(sa.text(f"DROP ROLE IF EXISTS {quote(role)}"))
        admin.dispose()
