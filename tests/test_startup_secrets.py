"""The server refuses to start on a guessable secret or an unsafe forwarded-header setting."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime

import itsdangerous
import pytest
from fastapi.testclient import TestClient

from immich_memories.config_loader import Config
from immich_memories.startup_checks import StartupRefused, startup_warnings

_STRONG = "6f1c0e9a4b7d2c58e3a1f0b9d8c7e6a5"


def _app(monkeypatch: pytest.MonkeyPatch, config: Config, **env: str):
    from immich_memories.web import server

    # WHY: the config file on the host is the boundary; each test states the config it needs.
    monkeypatch.setattr(server, "get_config", lambda *_a, **_k: config)
    monkeypatch.setattr("immich_memories.web.session.get_config", lambda *_a, **_k: config)
    monkeypatch.setattr("immich_memories.web.dependencies.get_config", lambda *_a, **_k: config)
    monkeypatch.setenv("IMMICH_MEMORIES_STORAGE_SECRET", _STRONG)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return server.create_app()


def _basic(**server: object) -> Config:
    auth = {"enabled": True, "provider": "basic", "username": "op", "password": "pw-1234567890"}
    return Config(auth=auth, server=server or {})


@pytest.mark.parametrize(
    "secret", ["change-me", "s" * 31, "change-me-" * 4, "a-long-example-value-0123456789abc"]
)
def test_a_weak_storage_secret_stops_the_server(monkeypatch, secret):
    with pytest.raises(StartupRefused, match="openssl rand -hex 32"):
        _app(monkeypatch, _basic(), IMMICH_MEMORIES_STORAGE_SECRET=secret)


def test_a_forged_cookie_needs_a_secret_the_server_refuses_to_run_with(monkeypatch):
    payload = {"authenticated": True, "username": "attacker", "auth_provider": "basic"}
    payload["authenticated_at"] = datetime.now(UTC).isoformat()
    signed = base64.b64encode(json.dumps(payload).encode())
    cookie = itsdangerous.TimestampSigner("change-me").sign(signed).decode()

    with pytest.raises(StartupRefused):
        _app(monkeypatch, _basic(), IMMICH_MEMORIES_STORAGE_SECRET="change-me")  # noqa: S106 — synthetic

    client = TestClient(_app(monkeypatch, _basic()), follow_redirects=False)
    client.cookies.set("session", cookie)
    assert client.get("/api/v1/connection").status_code == 401


def test_a_random_32_character_storage_secret_starts(monkeypatch):
    client = TestClient(_app(monkeypatch, _basic()), follow_redirects=False)

    assert client.get("/health/live").status_code == 200


def test_a_short_trigger_token_stops_the_server(monkeypatch):
    with pytest.raises(StartupRefused, match="trigger_token"):
        _app(monkeypatch, _basic(trigger_token="0123456789"))  # noqa: S106


def test_an_unset_trigger_token_is_fine(monkeypatch):
    assert _app(monkeypatch, _basic(trigger_token=""))


def test_a_wildcard_forwarded_allow_ips_with_auth_on_stops_the_server(monkeypatch):
    with pytest.raises(StartupRefused, match="list your proxy's address"):
        _app(monkeypatch, _basic(), FORWARDED_ALLOW_IPS="*")


def test_a_wildcard_forwarded_allow_ips_with_auth_off_starts(monkeypatch):
    assert _app(monkeypatch, Config(), FORWARDED_ALLOW_IPS="*")


def test_header_auth_with_forwarded_allow_ips_stops_the_server(monkeypatch):
    config = Config(auth={"enabled": True, "provider": "header", "trusted_proxies": ["10.0.0.2"]})

    with pytest.raises(StartupRefused, match="auth.trusted_proxies"):
        _app(monkeypatch, config, FORWARDED_ALLOW_IPS="10.0.0.2")


def test_a_short_basic_password_is_a_warning_not_a_refusal(monkeypatch):
    config = Config(
        auth={"enabled": True, "provider": "basic", "username": "op", "password": "short"}
    )

    assert _app(monkeypatch, config)
    assert any("12 characters" in warning for warning in startup_warnings(config))


def test_a_12_character_basic_password_raises_no_warning():
    assert startup_warnings(_basic()) == []


def test_ui_command_exits_with_the_refusal_instead_of_serving(monkeypatch, capsys):
    from immich_memories.web import server

    # WHY: the config file on the host is the boundary; the test states the config it needs.
    monkeypatch.setattr(server, "get_config", lambda *_a, **_k: _basic())
    monkeypatch.setenv("IMMICH_MEMORIES_STORAGE_SECRET", "change-me")

    with pytest.raises(SystemExit) as exited:
        server.main(port=0)

    assert exited.value.code == 1
    assert "openssl rand -hex 32" in capsys.readouterr().err
