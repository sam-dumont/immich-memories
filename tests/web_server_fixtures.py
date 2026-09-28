"""The real web server (middleware, session, sign-in routes) over a given config, for tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from immich_memories.config_loader import Config


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


def server_client(monkeypatch: pytest.MonkeyPatch, config: Config) -> TestClient:
    """A client over `create_app()`; the lifespan (scheduler, config dir) is not started."""
    from immich_memories.web import server

    # WHY: the config file on the host is the boundary; each test states the config it needs.
    monkeypatch.setattr(server, "get_config", lambda *_a, **_k: config)
    monkeypatch.setattr("immich_memories.web.session.get_config", lambda *_a, **_k: config)
    monkeypatch.setattr("immich_memories.web.health.get_config", lambda *_a, **_k: config)
    monkeypatch.setattr("immich_memories.web.trigger.get_config", lambda *_a, **_k: config)
    monkeypatch.setattr("immich_memories.web.dependencies.get_config", lambda *_a, **_k: config)
    monkeypatch.setenv("IMMICH_MEMORIES_STORAGE_SECRET", "test-session-secret")
    return TestClient(server.create_app(), follow_redirects=False)
