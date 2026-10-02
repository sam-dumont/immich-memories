"""A saved credential only goes to the URL it was saved with: a new URL needs a credential typed for it."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient

from immich_memories.config_loader import get_config, load_config, set_config
from immich_memories.settings_edit import SettingRefused, save_settings

MOVED = "The server URL changed: enter the credential for the new server."
STORED_KEY = "stored-key-0123456789abcdef"
NEW_URL = "https://elsewhere.example.test"

# (url key, its secret, a first URL to store it with)
PAIRS = [
    ("immich.url", "immich.api_key", "https://photos.example.test"),
    ("llm.base_url", "llm.api_key", "https://llm.example.test/v1"),
    (
        "editorial.preparation.caption_base_url",
        "editorial.preparation.caption_api_key",
        "https://captions.example.test/v1",
    ),
    ("musicgen.base_url", "musicgen.api_key", "https://musicgen.example.test"),
    ("ace_step.api_url", "ace_step.api_key", "https://acestep.example.test"),
    ("render.worker_base_url", "render.worker_token", "https://worker.example.test"),
]


@pytest.fixture
def config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("IMMICH_MEMORIES_SECRET_KEY", "k" * 40)
    monkeypatch.setenv("IMMICH_MEMORIES_STORAGE_SECRET", "s" * 40)
    path = tmp_path / "config.yaml"
    path.write_text("")
    load_config(path)
    yield path
    set_config(None)


def _value(key: str) -> object:
    value: object = get_config(reload=True)
    for part in key.split("."):
        value = getattr(value, part)
    return value


@pytest.mark.parametrize(("url_key", "secret_key", "first_url"), PAIRS)
def test_a_new_url_without_its_credential_is_refused(config_path, url_key, secret_key, first_url):
    save_settings({url_key: first_url, secret_key: STORED_KEY})

    with pytest.raises(SettingRefused, match="enter the credential for the new server"):
        save_settings({url_key: NEW_URL})

    assert _value(url_key) == first_url


@pytest.mark.parametrize(("url_key", "secret_key", "first_url"), PAIRS)
def test_a_new_url_with_a_new_credential_is_saved(config_path, url_key, secret_key, first_url):
    save_settings({url_key: first_url, secret_key: STORED_KEY})

    save_settings({url_key: NEW_URL, secret_key: "new-key-for-the-new-server-0123"})

    assert _value(url_key) == NEW_URL


@pytest.mark.parametrize(("url_key", "secret_key", "first_url"), PAIRS[:-1])
def test_a_new_url_is_saved_alone_when_no_credential_is_set(
    config_path, url_key, secret_key, first_url
):
    save_settings({url_key: NEW_URL})

    assert _value(url_key) == NEW_URL


def test_the_render_worker_url_always_needs_its_token(config_path):
    with pytest.raises(SettingRefused, match="enter the credential for the new server"):
        save_settings({"render.worker_base_url": NEW_URL})


def test_an_extra_account_url_needs_its_key_retyped(config_path):
    first = {"family": {"url": "https://photos.example.test", "api_key": STORED_KEY}}
    save_settings({"immich.accounts": first})

    with pytest.raises(SettingRefused, match="enter the credential for the new server"):
        save_settings({"immich.accounts": {"family": {"url": NEW_URL, "api_key": STORED_KEY}}})
    save_settings(
        {"immich.accounts": {"family": {"url": NEW_URL, "api_key": "new-key-0123456789"}}}
    )

    assert _value("immich.accounts")["family"].url == NEW_URL


def test_the_settings_form_refuses_a_new_immich_url_without_a_key(config_path):
    from immich_memories.web.server import create_app

    save_settings({"immich.url": "http://immich.lan:2283", "immich.api_key": STORED_KEY})
    client = TestClient(create_app(), follow_redirects=False)

    response = client.post("/api/v1/settings", json={"values": {"immich.url": NEW_URL}})

    assert response.status_code == 422
    assert response.json()["detail"].endswith(MOVED)
    assert _value("immich.url") == "http://immich.lan:2283"


def test_the_cli_refuses_a_new_immich_url_without_a_key(config_path):
    from immich_memories.cli import main

    save_settings({"immich.url": "http://immich.lan:2283", "immich.api_key": STORED_KEY})

    result = CliRunner().invoke(main, ["--config", str(config_path), "config", "--url", NEW_URL])

    assert result.exit_code != 0
    assert "enter the credential for the new server" in result.output
    assert _value("immich.url") == "http://immich.lan:2283"
