"""The sign-in limiter: per address as uvicorn resolved it, per username, and overall."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from immich_memories.config_loader import Config
from immich_memories.web.auth import is_rate_limited, record_failed_login, reset_rate_limiter

_PEER = "10.0.0.2"
_AUTH = {"enabled": True, "provider": "basic", "username": "op", "password": "pw-1234567890"}


@pytest.fixture(autouse=True)
def _fresh_limiter():
    reset_rate_limiter()
    yield
    reset_rate_limiter()


def _client(monkeypatch: pytest.MonkeyPatch, peer: str = _PEER, **auth: object) -> TestClient:
    from immich_memories.web import server

    config = Config(auth={**_AUTH, **auth})
    # WHY: the config file on the host is the boundary; each test states the config it needs.
    monkeypatch.setattr(server, "get_config", lambda *_a, **_k: config)
    monkeypatch.setenv("IMMICH_MEMORIES_STORAGE_SECRET", "test-session-key-0f3a9c2e7b41d856e0")
    return TestClient(server.create_app(), follow_redirects=False, client=(peer, 40000))


def _login(client: TestClient, password: str, username: str = "op", **headers: str) -> int:
    body = {"username": username, "password": password}
    return client.post("/auth/login", json=body, headers=headers).status_code


def test_a_forwarded_for_header_never_picks_the_limiter_bucket(monkeypatch):
    # The peer is even a trusted proxy: uvicorn, not the app, decides what X-Forwarded-For means.
    client = _client(monkeypatch, trusted_proxies=[_PEER])

    codes = [
        _login(client, f"guess{i}", **{"X-Forwarded-For": f"198.51.100.{i}"}) for i in range(7)
    ]

    assert codes[:5] == [401] * 5
    assert codes[5:] == [429, 429]


def test_one_username_backs_off_across_addresses(monkeypatch):
    for i in range(5):
        assert _login(_client(monkeypatch, peer=f"192.0.2.{i}"), f"guess{i}") == 401

    elsewhere = _client(monkeypatch, peer="192.0.2.200")

    assert _login(elsewhere, "pw-1234567890") == 429
    assert _login(elsewhere, "pw-1234567890", username="someone-else") == 401


def test_too_many_failures_overall_pause_every_sign_in(monkeypatch):
    for i in range(100):
        record_failed_login(f"203.0.113.{i % 250}", username=f"user{i}")

    assert _login(_client(monkeypatch, peer="192.0.2.77"), "pw-1234567890") == 429


def test_ipv6_addresses_in_one_slash_64_share_a_bucket():
    for i in range(5):
        record_failed_login(f"2001:db8:1:2::{i + 1:x}")

    assert is_rate_limited("2001:db8:1:2:ffff::1")
    assert not is_rate_limited("2001:db8:1:3::1")


def test_the_limiter_forgets_the_least_recent_sources_past_its_bound():
    for _ in range(5):
        record_failed_login("192.0.2.1")
    assert is_rate_limited("192.0.2.1")

    for i in range(20_000):
        record_failed_login(f"10.{i // 65536}.{(i // 256) % 256}.{i % 256}")

    assert not is_rate_limited("192.0.2.1")
