"""The settings page's and the connection panel's save handlers, and `config show`.

They go through the same store as the app, on both backends; no browser is involved.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from immich_memories.cli import main
from immich_memories.config_loader import load_config, set_config
from immich_memories.config_sources import describe_settings
from immich_memories.db import StoreLocation, open_store
from immich_memories.settings_store import SECRET_KEY_ENV, SettingsStore
from immich_memories.ui.pages.settings_config import save_form
from immich_memories.ui.pages.step1_config import connection_changes

SECRET_KEY = "test-only-secret-key-0123456789abcdef"  # noqa: S105 — synthetic


@pytest.fixture
def config_path(location: StoreLocation, tmp_path: Path, monkeypatch) -> Iterator[Path]:
    monkeypatch.setenv("IMMICH_MEMORIES_DATABASE_URL", location.url)
    monkeypatch.setenv("IMMICH_MEMORIES_DATABASE_SCHEMA", location.schema)
    monkeypatch.setenv(SECRET_KEY_ENV, SECRET_KEY)
    for name in ("IMMICH_URL", "IMMICH_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    path = tmp_path / "config.yaml"
    path.write_text("advanced:\n  llm:\n    model: file-model\n")
    load_config(path)
    yield path
    set_config(None)


def _stored(location: StoreLocation) -> dict:
    return SettingsStore(open_store(location=location), SECRET_KEY).values()


def test_the_page_saves_only_what_changed_to_the_database(config_path, location):
    before = config_path.read_bytes()
    entries = describe_settings()

    refusal = save_form(
        entries,
        {
            "output.resolution": "4k",
            "automation.enabled": False,
            "defaults.transition_duration": "0.8",
        },
    )

    assert refusal is None
    assert config_path.read_bytes() == before
    assert _stored(location) == {"output.resolution": "4k", "defaults.transition_duration": 0.8}


def test_the_page_never_saves_a_greyed_out_setting(config_path, location):
    refusal = save_form(describe_settings(), {"llm.model": "typed-anyway"})

    assert refusal is None
    assert _stored(location) == {}


def test_a_blank_secret_keeps_the_stored_one(config_path, location):
    assert save_form(describe_settings(), {"immich.api_key": "first-synthetic-key"}) is None

    assert save_form(describe_settings(), {"immich.api_key": ""}) is None

    assert _stored(location) == {"immich.api_key": "first-synthetic-key"}


def test_without_the_secret_key_the_page_says_what_to_do(config_path, monkeypatch):
    monkeypatch.delenv(SECRET_KEY_ENV)

    refusal = save_form(describe_settings(), {"immich.api_key": "a-synthetic-key"})

    assert refusal is not None
    assert SECRET_KEY_ENV in refusal
    assert "environment or config.yaml" in refusal


def test_the_connection_panel_saves_only_the_field_that_changed(config_path):
    config = load_config(config_path)
    state = SimpleNamespace(
        config=config, immich_url="http://immich.invalid:2283", immich_api_key=""
    )

    assert connection_changes(state) == {"immich.url": "http://immich.invalid:2283"}


def test_config_show_names_every_source(config_path, monkeypatch):
    monkeypatch.setenv("IMMICH_MEMORIES_OUTPUT__RESOLUTION", "720p")
    load_config(config_path)

    result = CliRunner().invoke(
        main, ["--config", str(config_path), "config", "show", "llm.model", "output.resolution"]
    )

    assert result.exit_code == 0, result.output
    assert "advanced.llm.model" in result.output
    assert "IMMICH_MEMORIES_OUTPUT__RESOLUTION" in result.output


def test_the_cli_stops_with_the_reason_when_the_store_cannot_be_read(tmp_path, monkeypatch):
    monkeypatch.setenv("IMMICH_MEMORIES_DATABASE_URL", "postgresql://u:synthetic-pw@127.0.0.1:1/db")
    path = tmp_path / "config.yaml"
    path.write_text("")

    result = CliRunner().invoke(main, ["--config", str(path), "config", "show"])
    set_config(None)

    assert result.exit_code == 1
    assert "127.0.0.1:1" in result.output
    assert "synthetic-pw" not in result.output


def test_the_ui_server_refuses_to_start_when_the_store_cannot_be_read(tmp_path, monkeypatch):
    from immich_memories.ui import app

    monkeypatch.setenv("IMMICH_MEMORIES_DATABASE_URL", "postgresql://u:synthetic-pw@127.0.0.1:1/db")
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path))
    set_config(None)

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        free_port = probe.getsockname()[1]
    # WHY: ui.run would start a real server; it must never be reached here.
    monkeypatch.setattr(app.ui, "run", lambda **_kwargs: pytest.fail("the server started"))

    with pytest.raises(SystemExit) as stopped:
        app.main(port=free_port, host="127.0.0.1")

    assert stopped.value.code == 1
