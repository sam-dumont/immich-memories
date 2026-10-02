"""The real web server (middleware, session, sign-in routes) over a given config, for tests."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime

import itsdangerous
import pytest
from fastapi.testclient import TestClient

from immich_memories.config_loader import Config

SESSION_SECRET = "test-session-key-0f3a9c2e7b41d856e0"  # noqa: S105 -- throwaway test key


def basic_auth_config(**server: object) -> Config:
    return Config(
        auth={
            "enabled": True,
            "provider": "basic",
            "username": "operator",
            "password": "test-password",
        },
        server=server or {},
    )


def server_client(
    monkeypatch: pytest.MonkeyPatch, config: Config, client: tuple[str, int] = ("testclient", 50000)
) -> TestClient:
    """A client over `create_app()`; the lifespan (scheduler, config dir) is not started."""
    from immich_memories.web import server

    # WHY: the config file on the host is the boundary; each test states the config it needs.
    monkeypatch.setattr(server, "get_config", lambda *_a, **_k: config)
    monkeypatch.setattr("immich_memories.web.session.get_config", lambda *_a, **_k: config)
    monkeypatch.setattr("immich_memories.web.health.get_config", lambda *_a, **_k: config)
    monkeypatch.setattr("immich_memories.web.trigger.get_config", lambda *_a, **_k: config)
    monkeypatch.setattr("immich_memories.web.dependencies.get_config", lambda *_a, **_k: config)
    monkeypatch.setenv("IMMICH_MEMORIES_STORAGE_SECRET", SESSION_SECRET)
    return TestClient(server.create_app(), follow_redirects=False, client=client)


def signed_session(config: Config, **fields: object) -> str:
    """A session cookie as the server signs it: signed in as the configured user, stamped."""
    from immich_memories.web.session_validity import auth_fingerprint

    session = {
        "authenticated": True,
        "username": config.auth.username or "operator",
        "auth_provider": config.auth.provider,
        "email": "",
        "authenticated_at": datetime.now(UTC).isoformat(),
        "session_generation": 0,
        "auth_fingerprint": auth_fingerprint(config.auth, SESSION_SECRET),
        **fields,
    }
    data = base64.b64encode(json.dumps(session).encode())
    return itsdangerous.TimestampSigner(SESSION_SECRET).sign(data).decode()
