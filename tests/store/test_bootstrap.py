"""Where the store lives: env beats config.yaml beats the default, and a URL never leaks a password."""

from __future__ import annotations

from pathlib import Path

import pytest

from immich_memories.config_loader import Config
from immich_memories.db import StoreLocation, redact_url, resolve_location


@pytest.fixture(autouse=True)
def _no_store_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("IMMICH_MEMORIES_DATABASE_URL", "IMMICH_MEMORIES_DATABASE_SCHEMA"):
        monkeypatch.delenv(name, raising=False)


def test_unset_defaults_to_a_sqlite_file_under_the_current_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))

    location = resolve_location(Config())

    assert location == StoreLocation(
        url=f"sqlite:///{tmp_path / '.immich-memories' / 'store.db'}", schema="immich_memories"
    )


def test_config_yaml_names_the_database():
    config = Config()
    config.database.url = "postgresql://memories@db/photos"
    config.database.schema_name = "memories"

    assert resolve_location(config) == StoreLocation(
        url="postgresql+psycopg://memories@db/photos", schema="memories"
    )


def test_environment_beats_config_yaml(monkeypatch):
    config = Config()
    config.database.url = "postgresql://memories@db/photos"
    monkeypatch.setenv("IMMICH_MEMORIES_DATABASE_URL", "sqlite:////data/store.db")
    monkeypatch.setenv("IMMICH_MEMORIES_DATABASE_SCHEMA", "other")

    assert resolve_location(config) == StoreLocation(url="sqlite:////data/store.db", schema="other")


def test_a_home_relative_sqlite_path_follows_home_per_call(monkeypatch, tmp_path):
    monkeypatch.setenv("IMMICH_MEMORIES_DATABASE_URL", "sqlite:///~/elsewhere/store.db")
    monkeypatch.setenv("HOME", str(tmp_path / "a"))
    first = resolve_location(Config())
    monkeypatch.setenv("HOME", str(tmp_path / "b"))
    second = resolve_location(Config())

    assert first.sqlite_path == tmp_path / "a" / "elsewhere" / "store.db"
    assert second.sqlite_path == tmp_path / "b" / "elsewhere" / "store.db"


def test_a_postgres_location_has_no_sqlite_path():
    location = StoreLocation(url="postgresql+psycopg://u@h/d", schema="immich_memories")

    assert location.sqlite_path is None
    assert location.dialect_name == "postgresql"


def test_redaction_hides_the_password_and_keeps_the_rest():
    shown = redact_url("postgresql+psycopg://memories:hunter2@db.lan:5432/photos")

    assert "hunter2" not in shown
    assert shown == "postgresql+psycopg://memories:***@db.lan:5432/photos"


def test_a_location_shows_itself_redacted():
    location = StoreLocation(url="postgresql+psycopg://u:s3cret@h/d", schema="immich_memories")

    assert "s3cret" not in repr(location)
    assert "s3cret" not in str(location)


def test_an_unparseable_url_is_refused_without_echoing_it():
    with pytest.raises(ValueError) as error:
        resolve_location_from("not a url with p4ss")

    assert "p4ss" not in str(error.value)


def resolve_location_from(url: str) -> StoreLocation:
    config = Config()
    config.database.url = url
    return resolve_location(config)


def test_sqlite_path_is_a_path_object(tmp_path):
    location = StoreLocation(url=f"sqlite:///{tmp_path}/s.db", schema="immich_memories")

    assert isinstance(location.sqlite_path, Path)


def test_a_sqlite_url_in_the_environment_needs_no_config_file(monkeypatch, tmp_path):
    monkeypatch.setenv("IMMICH_MEMORIES_DATABASE_URL", f"sqlite:///{tmp_path / 'store.db'}")
    monkeypatch.delenv("IMMICH_MEMORIES_DATABASE_SCHEMA", raising=False)

    def unreadable():
        raise AssertionError("the environment names the store; config.yaml is not read")

    # WHY: get_config reads config.yaml from the home directory; the environment decides here.
    monkeypatch.setattr("immich_memories.config_loader.get_config", unreadable)

    assert resolve_location().url == f"sqlite:///{tmp_path / 'store.db'}"
