"""The Immich connection in Settings: the stored key never leaves the server, nor follows a new URL."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from immich_memories.config_loader import Config
from immich_memories.web.dependencies import config_file, immich_greeter
from tests.web_api_fixtures import api_client, config_in

STORED_URL = "https://photos.example.test"
STORED_KEY = "stored-key-0123456789"


@pytest.fixture
def config(tmp_path: Path) -> Config:
    config = config_in(tmp_path)
    config.immich.url = STORED_URL
    config.immich.api_key = STORED_KEY
    return config


@pytest.fixture
def greeted() -> list[tuple[str, str]]:
    return []


@pytest.fixture
def client(config: Config, tmp_path: Path, greeted) -> TestClient:
    client = api_client(config)

    def greet(url: str, key: str, _version: str) -> str:
        greeted.append((url, key))
        return "Alex"

    # WHY: the greeter is the network read against Immich; the e2e smoke covers a real server.
    client.app.dependency_overrides[immich_greeter] = lambda: greet
    client.app.dependency_overrides[config_file] = lambda: tmp_path / "config.yaml"
    return client


def test_the_connection_says_a_key_is_stored_without_sending_it(client):
    connection = client.get("/api/v1/connection").json()

    assert connection == {"url": STORED_URL, "has_key": True}
    assert STORED_KEY not in client.get("/api/v1/connection").text


def test_testing_the_stored_server_uses_the_stored_key(client, greeted):
    answer = client.post("/api/v1/connection/test", json={"url": STORED_URL + "/", "api_key": ""})

    assert answer.json() == {"user": "Alex"}
    assert greeted == [(STORED_URL + "/", STORED_KEY)]


def test_a_new_url_without_a_new_key_is_refused_before_any_call(client, greeted):
    answer = client.post(
        "/api/v1/connection/test", json={"url": "http://127.0.0.1:9", "api_key": ""}
    )

    assert answer.status_code == 422
    assert "enter the API key for the new server" in answer.json()["detail"]
    assert greeted == []


def test_saving_a_new_server_with_its_key_writes_the_config(client, config, tmp_path):
    answer = client.put(
        "/api/v1/connection", json={"url": "https://new.example.test", "api_key": "new-key"}
    )

    assert answer.json() == {"url": "https://new.example.test", "has_key": True}
    saved = yaml.safe_load((tmp_path / "config.yaml").read_text())
    assert saved["immich"]["url"] == "https://new.example.test"
    assert saved["immich"]["api_key"] == "new-key"


def test_saving_a_new_url_alone_changes_nothing(client, config, tmp_path):
    answer = client.put("/api/v1/connection", json={"url": "https://elsewhere.test", "api_key": ""})

    assert answer.status_code == 422
    assert config.immich.url == STORED_URL
    assert not (tmp_path / "config.yaml").exists()
