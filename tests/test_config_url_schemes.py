"""Every server the config points at is an http:// or https:// URL, or unset."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from immich_memories.config_loader import Config

_URL_KEYS = [
    "immich:\n  url: {url}\n",
    "immich:\n  accounts:\n    partner:\n      url: {url}\n",
    "advanced:\n  llm:\n    base_url: {url}\n",
    "advanced:\n  musicgen:\n    base_url: {url}\n",
    "advanced:\n  ace_step:\n    api_url: {url}\n",
    "network:\n  geocoding_url: {url}\n",
    "advanced:\n  auth:\n    issuer_url: {url}\n",
]


def _load(tmp_path: Path, text: str) -> Config:
    path = tmp_path / "config.yaml"
    path.write_text(text)
    return Config.from_yaml(path)


@pytest.mark.parametrize("template", _URL_KEYS)
@pytest.mark.parametrize("url", ["'javascript:alert(1)'", "file:///etc/passwd", "immich.lan:2283"])
def test_a_server_url_that_is_not_http_is_refused_at_load(tmp_path, template, url):
    with pytest.raises(ValidationError, match="http"):
        _load(tmp_path, template.format(url=url))


@pytest.mark.parametrize("template", _URL_KEYS)
@pytest.mark.parametrize("url", ["http://immich.lan:2283", "https://photos.example.org/api", "''"])
def test_an_http_url_or_none_at_all_still_loads(tmp_path, template, url):
    _load(tmp_path, template.format(url=url))


@pytest.mark.parametrize("template", _URL_KEYS)
def test_a_url_naming_an_unset_variable_does_not_stop_the_config_loading(
    tmp_path, template, monkeypatch
):
    monkeypatch.delenv("IMMICH_MEMORIES_TEST_UNSET_URL", raising=False)
    _load(tmp_path, template.format(url="'${IMMICH_MEMORIES_TEST_UNSET_URL}'"))


def test_a_server_url_that_is_not_http_is_refused_when_saved(tmp_path):
    from immich_memories.config_loader import load_config, set_config
    from immich_memories.web.dependencies import config_file
    from tests.web_api_fixtures import api_client, config_in

    path = tmp_path / "config.yaml"
    path.write_text("")
    load_config(path)
    client = api_client(config_in(tmp_path))
    client.app.dependency_overrides[config_file] = lambda: path
    try:
        refused = client.post(
            "/api/v1/settings", json={"values": {"network.geocoding_url": "file:///etc/passwd"}}
        )
        saved = client.post(
            "/api/v1/settings",
            json={"values": {"network.geocoding_url": "https://geo.example.org/search"}},
        )
    finally:
        set_config(None)

    assert refused.status_code == 422 and "http" in refused.json()["detail"]
    assert saved.status_code == 200
