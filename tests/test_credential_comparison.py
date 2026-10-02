"""Credentials compare as bytes: any text a caller types is a match or a counted failure."""

from __future__ import annotations

import pytest

from immich_memories.config_loader import Config
from immich_memories.web.auth import is_rate_limited, reset_rate_limiter
from tests.web_server_fixtures import server_client

_TOKEN = "tok-0123456789abcdef0123456789abcdef"  # noqa: S105


def _config(password: str = "pw-1234567890") -> Config:  # noqa: S107
    return Config(
        auth={"enabled": True, "provider": "basic", "username": "op", "password": password},
        server={"trigger_token": _TOKEN},
    )


@pytest.fixture(autouse=True)
def _fresh_limiter():
    reset_rate_limiter()
    yield
    reset_rate_limiter()


def test_a_non_ascii_wrong_password_is_refused_and_counted(monkeypatch):
    client = server_client(monkeypatch, _config())

    codes = [
        client.post("/auth/login", json={"username": "op", "password": f"gü{i}"}).status_code
        for i in range(5)
    ]

    assert codes == [401] * 5
    assert is_rate_limited("testclient")


def test_a_non_ascii_correct_password_signs_in(monkeypatch):
    client = server_client(monkeypatch, _config(password="pässwörd-çà-1234"))

    response = client.post("/auth/login", json={"username": "op", "password": "pässwörd-çà-1234"})

    assert response.status_code == 200


def test_a_non_ascii_trigger_token_is_unauthorised_not_an_error(monkeypatch):
    client = server_client(monkeypatch, _config())

    response = client.post("/api/trigger", headers={"x-api-key": "t\xf6k".encode("latin-1")})

    assert response.status_code == 401
