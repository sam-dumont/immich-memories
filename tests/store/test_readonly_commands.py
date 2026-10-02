"""Inspecting an old store must not upgrade it before the command runs."""

import pytest
from click.testing import CliRunner

from immich_memories.cli import main
from immich_memories.db import StoreLocation, close_stores, open_store
from immich_memories.db.backup import read_manifest
from immich_memories.db.migrate import current_revisions, downgrade
from immich_memories.db.store import unmigrated_store
from immich_memories.settings_store import SettingsStore


def test_status_loads_saved_settings_without_upgrading_the_store(tmp_path, monkeypatch):
    path = tmp_path / "store.db"
    location = StoreLocation(url=f"sqlite:///{path}")
    monkeypatch.setenv("IMMICH_MEMORIES_DATABASE_URL", location.url)
    store = open_store(location=location)
    SettingsStore(store, None).save({"output.resolution": "720p"})
    downgrade(store, "0010_run_film_timeline")
    close_stores()

    result = CliRunner().invoke(
        main, ["--config", str(tmp_path / "config.yaml"), "store", "status"]
    )
    assert result.exit_code == 0, result.output
    untouched = unmigrated_store(location)
    try:
        assert current_revisions(untouched) == ("0010_run_film_timeline",)
    finally:
        untouched.engine.dispose()
    assert "app expects" in result.output


@pytest.mark.parametrize("command", [["config", "show", "output.resolution"], ["preflight"]])
def test_other_readonly_commands_keep_the_old_revision(tmp_path, monkeypatch, command):
    path = tmp_path / "store.db"
    location = StoreLocation(url=f"sqlite:///{path}")
    monkeypatch.setenv("IMMICH_MEMORIES_DATABASE_URL", location.url)
    store = open_store(location=location)
    SettingsStore(store, None).save({"output.resolution": "720p"})
    downgrade(store, "0010_run_film_timeline")
    close_stores()
    if command[0] == "preflight":
        monkeypatch.setenv("IMMICH_MEMORIES_NOTIFICATIONS__ENABLED", "true")
        monkeypatch.setenv("IMMICH_MEMORIES_NOTIFICATIONS__URLS", '["mailto:test@example.com"]')
    result = CliRunner().invoke(main, ["--config", str(tmp_path / "config.yaml"), *command])
    assert "app expects" in result.output
    if command[0] == "config":
        assert result.exit_code == 0, result.output
        assert "720p" in result.output
    untouched = unmigrated_store(location)
    try:
        assert current_revisions(untouched) == ("0010_run_film_timeline",)
    finally:
        untouched.engine.dispose()


def test_backup_records_the_original_revision(tmp_path, monkeypatch):
    location = StoreLocation(url=f"sqlite:///{tmp_path / 'store.db'}")
    monkeypatch.setenv("IMMICH_MEMORIES_DATABASE_URL", location.url)
    store = open_store(location=location)
    downgrade(store, "0010_run_film_timeline")
    close_stores()
    backup = tmp_path / "old.backup"
    result = CliRunner().invoke(
        main, ["--config", str(tmp_path / "config.yaml"), "store", "backup", "--to", str(backup)]
    )
    assert result.exit_code == 0, result.output
    assert read_manifest(backup).revisions == ["0010_run_film_timeline"]


def test_a_store_before_saved_settings_can_still_be_inspected(tmp_path, monkeypatch):
    location = StoreLocation(url=f"sqlite:///{tmp_path / 'store.db'}")
    monkeypatch.setenv("IMMICH_MEMORIES_DATABASE_URL", location.url)
    store = open_store(location=location)
    downgrade(store, "0001_foundation")
    close_stores()
    result = CliRunner().invoke(main, ["config", "show", "output.resolution"])
    assert result.exit_code == 0, result.output
    untouched = unmigrated_store(location)
    try:
        assert current_revisions(untouched) == ("0001_foundation",)
    finally:
        untouched.engine.dispose()


def test_explicit_migrate_upgrades_the_old_store(tmp_path, monkeypatch):
    from immich_memories.db.migrate import heads

    location = StoreLocation(url=f"sqlite:///{tmp_path / 'store.db'}")
    monkeypatch.setenv("IMMICH_MEMORIES_DATABASE_URL", location.url)
    store = open_store(location=location)
    downgrade(store, "0010_run_film_timeline")
    close_stores()
    result = CliRunner().invoke(main, ["store", "migrate"])
    assert result.exit_code == 0, result.output
    untouched = unmigrated_store(location)
    try:
        assert current_revisions(untouched) == heads()
    finally:
        untouched.engine.dispose()


@pytest.mark.parametrize("command", ["ui", "generate", "auto"])
def test_writing_entrypoints_upgrade_before_their_command_body(tmp_path, monkeypatch, command):
    from immich_memories.db.migrate import heads

    location = StoreLocation(url=f"sqlite:///{tmp_path / 'store.db'}")
    monkeypatch.setenv("IMMICH_MEMORIES_DATABASE_URL", location.url)
    store = open_store(location=location)
    downgrade(store, "0010_run_film_timeline")
    close_stores()
    called = []

    def command_body(**kwargs):
        untouched = unmigrated_store(location)
        try:
            called.append(current_revisions(untouched))
        finally:
            untouched.engine.dispose()

    # Replace external work only; exercise the public CLI's real startup and config loader.
    args = [command]
    target = main.commands[command]
    if command == "auto":
        target = target.commands["status"]
        args.append("status")
    monkeypatch.setattr(target, "callback", command_body)
    result = CliRunner().invoke(main, ["--config", str(tmp_path / "config.yaml"), *args])
    assert result.exit_code == 0, result.output
    assert called == [heads()]


def test_config_inspection_does_not_create_a_missing_store(tmp_path, monkeypatch):
    path = tmp_path / "absent.db"
    monkeypatch.setenv("IMMICH_MEMORIES_DATABASE_URL", f"sqlite:///{path}")
    result = CliRunner().invoke(
        main, ["--config", str(tmp_path / "config.yaml"), "config", "show", "output.resolution"]
    )
    assert result.exit_code == 0, result.output
    assert not path.exists()


def test_a_newer_store_keeps_readable_saved_settings_without_migration(tmp_path, monkeypatch):
    import sqlalchemy as sa

    location = StoreLocation(url=f"sqlite:///{tmp_path / 'store.db'}")
    monkeypatch.setenv("IMMICH_MEMORIES_DATABASE_URL", location.url)
    store = open_store(location=location)
    SettingsStore(store, None).save({"output.resolution": "720p"})
    with store.begin() as connection:
        connection.execute(sa.text("UPDATE alembic_version SET version_num='future_revision'"))
    close_stores()
    result = CliRunner().invoke(
        main, ["--config", str(tmp_path / "config.yaml"), "config", "show", "output.resolution"]
    )
    assert result.exit_code == 0, result.output
    assert "720p" in result.output
    assert "future_revision" in result.output
    assert "app expects" in result.output
    untouched = unmigrated_store(location)
    try:
        assert current_revisions(untouched) == ("future_revision",)
    finally:
        untouched.engine.dispose()


def test_missing_required_settings_fails_instead_of_losing_overrides(tmp_path, monkeypatch):
    import sqlalchemy as sa

    location = StoreLocation(url=f"sqlite:///{tmp_path / 'store.db'}")
    monkeypatch.setenv("IMMICH_MEMORIES_DATABASE_URL", location.url)
    store = open_store(location=location)
    with store.begin() as connection:
        connection.execute(sa.text("DROP TABLE settings"))
    close_stores()
    result = CliRunner().invoke(
        main, ["--config", str(tmp_path / "config.yaml"), "config", "show", "output.resolution"]
    )
    assert result.exit_code != 0
    assert "settings table" in result.output
    assert "missing" in result.output
