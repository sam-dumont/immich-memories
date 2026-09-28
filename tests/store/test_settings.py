"""The settings layer: env > config.yaml > database > default, on both backends.

Synthetic values only. Each test points the app at the fixture's store through the
bootstrap variables, exactly as an operator would.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa

from immich_memories.config_loader import get_config, load_config, set_config
from immich_memories.config_sources import describe_settings
from immich_memories.db import StoreLocation, open_store
from immich_memories.db.tables import settings
from immich_memories.logging_config import SecretRedactionFilter
from immich_memories.settings_edit import SettingRefused, move_to_database, save_settings
from immich_memories.settings_store import (
    SECRET_KEY_ENV,
    SKIP_STORED_SETTINGS_ENV,
    SecretKeyError,
    SettingsStore,
    SettingsUnavailable,
)

SECRET_KEY = "test-only-secret-key-0123456789abcdef"  # noqa: S105 — synthetic
API_KEY = "synthetic-" * 3  # low entropy on purpose: gitleaks reads test literals too


@pytest.fixture
def config_path(location: StoreLocation, tmp_path: Path, monkeypatch) -> Iterator[Path]:
    monkeypatch.setenv("IMMICH_MEMORIES_DATABASE_URL", location.url)
    monkeypatch.setenv("IMMICH_MEMORIES_DATABASE_SCHEMA", location.schema)
    monkeypatch.setenv(SECRET_KEY_ENV, SECRET_KEY)
    for name in ("IMMICH_URL", "IMMICH_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    path = tmp_path / "config.yaml"
    path.write_text("")
    load_config(path)
    yield path
    set_config(None)


def _source(key: str):
    return next(entry for entry in describe_settings() if entry.key == key)


def _raw_row(location: StoreLocation, key: str):
    with open_store(location=location).connect() as conn:
        return conn.execute(sa.select(settings).where(settings.c.key == key)).mappings().one()


@pytest.mark.parametrize(
    ("key", "yaml_text", "file_name", "env_name", "values"),
    [
        (
            "llm.model",
            "advanced:\n  llm:\n    model: from-file\n",
            "advanced.llm.model",
            "IMMICH_MEMORIES_LLM__MODEL",
            ("from-db", "from-file", "from-env"),
        ),
        (
            "output.resolution",
            "output:\n  resolution: 720p\n",
            "output.resolution",
            "IMMICH_MEMORIES_OUTPUT__RESOLUTION",
            ("4k", "720p", "1080p"),
        ),
        (
            "editorial.preparation.caption_concurrency",
            "editorial:\n  preparation:\n    caption_concurrency: 3\n",
            "editorial.preparation.caption_concurrency",
            "IMMICH_MEMORIES_EDITORIAL__PREPARATION__CAPTION_CONCURRENCY",
            (2, 3, 5),
        ),
    ],
)
def test_env_beats_the_file_beats_the_database_beats_the_default(
    config_path, monkeypatch, key, yaml_text, file_name, env_name, values
):
    db_value, file_value, env_value = values
    default = _source(key)
    assert default.source == "default"

    save_settings({key: db_value})
    assert (_source(key).value, _source(key).source, _source(key).override) == (
        db_value,
        "database",
        None,
    )

    config_path.write_text(yaml_text)
    load_config(config_path)
    assert (_source(key).value, _source(key).source, _source(key).override) == (
        file_value,
        "file",
        file_name,
    )

    monkeypatch.setenv(env_name, str(env_value))
    load_config(config_path)
    assert (_source(key).value, _source(key).source, _source(key).override) == (
        env_value,
        "env",
        env_name,
    )


def test_a_tier_two_section_written_at_the_top_level_is_named_there(config_path):
    config_path.write_text("llm:\n  model: flat-file\n")
    load_config(config_path)

    assert _source("llm.model").override == "llm.model"


def test_a_shortcut_variable_is_named_as_the_override(config_path, monkeypatch):
    monkeypatch.setenv("IMMICH_URL", "http://immich.invalid:2283")
    load_config(config_path)

    entry = _source("immich.url")
    assert (entry.source, entry.override) == ("env", "IMMICH_URL")


def test_a_save_writes_the_database_and_never_the_file(config_path, location):
    config_path.write_text("output:\n  resolution: 720p\n")
    before = config_path.read_bytes()
    load_config(config_path)

    config = save_settings({"llm.model": "saved-model", "automation.cooldown_hours": 12})

    assert config_path.read_bytes() == before
    assert config.llm.model == "saved-model"
    assert config.automation.cooldown_hours == 12
    assert _raw_row(location, "automation.cooldown_hours")["value"] == 12
    assert get_config().llm.model == "saved-model"


def test_only_saved_keys_have_a_row(config_path, location):
    save_settings({"llm.model": "saved-model"})

    store = SettingsStore(open_store(location=location), SECRET_KEY)
    assert store.stored_keys() == {"llm.model"}


def test_a_key_the_file_sets_is_refused_and_the_refusal_names_it(config_path):
    config_path.write_text("advanced:\n  llm:\n    model: from-file\n")
    load_config(config_path)

    with pytest.raises(SettingRefused, match=r"advanced\.llm\.model"):
        save_settings({"llm.model": "ignored"})


def test_a_key_the_environment_sets_is_refused_and_the_refusal_names_it(config_path, monkeypatch):
    monkeypatch.setenv("IMMICH_MEMORIES_LLM__MODEL", "from-env")
    load_config(config_path)

    with pytest.raises(SettingRefused, match="IMMICH_MEMORIES_LLM__MODEL"):
        save_settings({"llm.model": "ignored"})


def test_an_invalid_value_is_refused_before_anything_is_written(config_path, location):
    with pytest.raises(SettingRefused, match="output.resolution"):
        save_settings({"llm.model": "fine", "output.resolution": "banana"})

    assert SettingsStore(open_store(location=location), SECRET_KEY).stored_keys() == set()


def test_bootstrap_keys_never_go_to_the_database(config_path):
    with pytest.raises(SettingRefused, match="database.url"):
        save_settings({"database.url": "sqlite:////elsewhere.db"})


def test_a_secret_is_encrypted_at_rest_and_read_back(config_path, location):
    save_settings({"immich.api_key": API_KEY})

    row = _raw_row(location, "immich.api_key")
    assert row["secret"] is True
    assert row["value"] is None
    assert API_KEY.encode() not in bytes(row["ciphertext"])
    assert load_config(config_path).immich.api_key == API_KEY
    assert _source("immich.api_key").value == "***"


def test_without_the_secret_key_a_secret_is_refused(config_path, location, monkeypatch):
    monkeypatch.delenv(SECRET_KEY_ENV)

    with pytest.raises(SettingRefused, match=SECRET_KEY_ENV):
        save_settings({"immich.api_key": API_KEY})
    with pytest.raises(SecretKeyError, match=SECRET_KEY_ENV):
        SettingsStore(open_store(location=location), None).save({"llm.api_key": API_KEY})


def test_a_short_secret_key_is_refused(location):
    with pytest.raises(SecretKeyError, match="at least 32"):
        SettingsStore(open_store(location=location), "short").save({"llm.api_key": API_KEY})


def test_a_secret_under_another_key_falls_back_to_the_default(config_path, monkeypatch, caplog):
    save_settings({"immich.api_key": API_KEY})
    monkeypatch.setenv(SECRET_KEY_ENV, "a-different-secret-key-9876543210fedcba")

    with caplog.at_level(logging.WARNING):
        config = load_config(config_path)

    assert config.immich.api_key == ""
    assert "immich.api_key" in caplog.text


def test_a_secret_from_the_database_is_redacted_from_logs(config_path):
    save_settings({"immich.api_key": API_KEY})
    load_config(config_path)
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "calling with %s", (API_KEY,), None)

    SecretRedactionFilter().filter(record)

    assert API_KEY not in record.getMessage()


def test_moving_a_key_out_of_the_file_keeps_the_rest_of_it(config_path, monkeypatch):
    monkeypatch.setenv("SYNTHETIC_IMMICH_KEY", API_KEY)
    config_path.write_text(
        "immich:\n  api_key: ${SYNTHETIC_IMMICH_KEY}\n"
        "advanced:\n  llm:\n    model: file-model\n    base_url: http://llm.invalid/v1\n"
    )
    load_config(config_path)

    backup = move_to_database(["llm.model"])

    text = config_path.read_text()
    assert "file-model" not in text
    assert "http://llm.invalid/v1" in text
    assert "${SYNTHETIC_IMMICH_KEY}" in text
    assert API_KEY not in text
    assert "file-model" in backup.read_text()
    entry = _source("llm.model")
    assert (entry.value, entry.source) == ("file-model", "database")


def test_moving_a_key_that_reads_the_environment_is_refused(config_path, monkeypatch):
    monkeypatch.setenv("SYNTHETIC_IMMICH_KEY", API_KEY)
    config_path.write_text("immich:\n  api_key: ${SYNTHETIC_IMMICH_KEY}\n")
    load_config(config_path)

    with pytest.raises(SettingRefused, match="environment variable"):
        move_to_database(["immich.api_key"])


def test_a_store_that_cannot_be_reached_stops_the_config_load(tmp_path, monkeypatch):
    # Port 1 refuses at once; the password must never reach the message.
    url = "postgresql://settings:hunter2-synthetic@127.0.0.1:1/immich_memories"
    monkeypatch.setenv("IMMICH_MEMORIES_DATABASE_URL", url)
    path = tmp_path / "config.yaml"
    path.write_text("")

    with pytest.raises(SettingsUnavailable) as raised:
        load_config(path)

    message = str(raised.value)
    assert "127.0.0.1:1" in message
    assert "hunter2-synthetic" not in message
    assert "IMMICH_MEMORIES_DATABASE_URL" in message
    assert SKIP_STORED_SETTINGS_ENV in message
    set_config(None)


def test_a_corrupt_store_file_stops_the_config_load(tmp_path, monkeypatch):
    database = tmp_path / "store.db"
    database.write_bytes(b"this is not a SQLite database" * 64)
    monkeypatch.setenv("IMMICH_MEMORIES_DATABASE_URL", f"sqlite:///{database}")
    path = tmp_path / "config.yaml"
    path.write_text("")

    with pytest.raises(SettingsUnavailable, match="store.db"):
        load_config(path)
    set_config(None)


def test_a_store_that_does_not_exist_yet_is_a_fresh_install(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("IMMICH_MEMORIES_DATABASE_URL", f"sqlite:///{tmp_path / 'store.db'}")
    path = tmp_path / "config.yaml"
    path.write_text("")

    with caplog.at_level(logging.WARNING, logger="immich_memories.settings_store"):
        config = load_config(path)
    set_config(None)

    assert config.llm.model == type(config.llm)().model
    assert caplog.records == []
    assert not (tmp_path / "store.db").exists()


def test_the_bypass_starts_without_saved_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("IMMICH_MEMORIES_DATABASE_URL", "postgresql://u:p@127.0.0.1:1/db")
    monkeypatch.setenv(SKIP_STORED_SETTINGS_ENV, "1")
    path = tmp_path / "config.yaml"
    path.write_text("advanced:\n  llm:\n    model: file-model\n")

    assert load_config(path).llm.model == "file-model"
    set_config(None)


def test_an_unreadable_secret_is_flagged_in_the_report(config_path, monkeypatch):
    save_settings({"immich.api_key": API_KEY})
    monkeypatch.setenv(SECRET_KEY_ENV, "a-different-secret-key-9876543210fedcba")
    load_config(config_path)

    entry = _source("immich.api_key")

    assert (entry.source, entry.unreadable) == ("database", True)
    assert not _source("llm.model").unreadable
