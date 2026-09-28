"""Tests for auth helpers (bypass paths, session management, is_auth_enabled) and the
server middleware that applies them."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from immich_memories.config_loader import Config
from immich_memories.config_models_auth import AuthConfig
from immich_memories.web.auth import (
    clear_session,
    is_auth_enabled,
    is_bypass_path,
    record_failed_login,
    reset_rate_limiter,
    set_session,
)
from tests.web_server_fixtures import basic_auth_config, server_client


class TestBypassPaths:
    """is_bypass_path identifies public paths correctly."""

    @pytest.mark.parametrize(
        "path",
        [
            "/health",
            "/health/live",
            "/health/ready",
            "/login",
            "/app/login",
            "/auth/login",
            "/logout",
            "/auth/callback",
            "/auth/authorize",
            "/api/v1/i18n",
            "/api/v1/session",
            "/app/_app/immutable/start.js",
            "/static/fonts/Montserrat.woff2",
        ],
    )
    def test_bypass_paths_return_true(self, path: str):
        assert is_bypass_path(path) is True

    @pytest.mark.parametrize(
        "path",
        [
            "/",
            "/step2",
            "/protected",
            "/settings/config",
            "/api/something",
            "/app/runs",
            # WHY: pictures and films stream through the API; they stay behind the login.
            "/api/v1/assets/0123456789abcdef/video",
            "/api/v1/assets/0123456789abcdef/thumbnail",
        ],
    )
    def test_protected_paths_return_false(self, path: str):
        assert is_bypass_path(path) is False


class TestProductionMiddleware:
    """Production ordering keeps operational probes independent from config."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("path", ["/health", "/health/live", "/health/ready"])
    async def test_health_bypasses_before_configuration_load(self, path: str, monkeypatch):
        from immich_memories.web import server

        request = MagicMock()
        request.url.path = path
        response = MagicMock(name="health_response")

        async def call_next(_request):
            return response

        get_config = MagicMock(side_effect=AssertionError("health loaded configuration"))
        # WHY: the config file is the boundary; a probe must not touch it at all.
        monkeypatch.setattr(server, "get_config", get_config)

        assert await server._auth_middleware(request, call_next) is response
        get_config.assert_not_called()

    def test_health_prefix_is_not_a_bypass(self, monkeypatch):
        client = server_client(monkeypatch, basic_auth_config())

        assert client.get("/health/live/extra").status_code == 307

    def test_a_signed_out_browser_goes_to_the_sign_in_page(self, monkeypatch):
        client = server_client(monkeypatch, basic_auth_config())

        response = client.get("/app/runs")

        assert response.status_code == 307
        assert response.headers["location"] == "/app/login"

    def test_a_signed_out_api_call_gets_401(self, monkeypatch):
        client = server_client(monkeypatch, basic_auth_config())

        assert client.get("/api/v1/runs").status_code == 401

    def test_signing_in_opens_the_protected_api(self, monkeypatch):
        reset_rate_limiter()
        client = server_client(monkeypatch, basic_auth_config())

        signed_in = client.post(
            "/auth/login", json={"username": "operator", "password": "test-password"}
        )

        assert signed_in.status_code == 200
        assert client.get("/api/v1/session").status_code == 200
        assert client.get("/app/runs").status_code != 307

    def test_a_wrong_password_is_401(self, monkeypatch):
        reset_rate_limiter()
        client = server_client(monkeypatch, basic_auth_config())

        refused = client.post("/auth/login", json={"username": "operator", "password": "nope"})

        assert refused.status_code == 401

    def test_login_still_applies_rate_limiting(self, monkeypatch):
        reset_rate_limiter()
        for _ in range(5):
            record_failed_login("testclient")
        client = server_client(monkeypatch, basic_auth_config())

        blocked = client.post(
            "/auth/login", json={"username": "operator", "password": "test-password"}
        )

        reset_rate_limiter()
        assert blocked.status_code == 429

    def test_auth_disabled_lets_everything_through(self, monkeypatch):
        client = server_client(monkeypatch, Config())

        assert client.get("/api/v1/session").status_code == 200


class TestSessionHelpers:
    """set_session and clear_session manage session dict correctly."""

    def test_set_session_fields(self):
        session: dict = {}
        set_session(session, username="admin", provider="basic", email="a@b.com")
        assert session["authenticated"] is True
        assert session["username"] == "admin"
        assert session["auth_provider"] == "basic"
        assert session["email"] == "a@b.com"
        assert "authenticated_at" in session

    def test_set_session_without_email(self):
        session: dict = {}
        set_session(session, username="admin", provider="oidc")
        assert session["authenticated"] is True
        assert session["email"] == ""

    def test_set_session_timestamp_is_utc_iso(self):
        session: dict = {}
        set_session(session, username="admin", provider="basic")
        ts = datetime.fromisoformat(session["authenticated_at"])
        assert ts.tzinfo is not None  # UTC-aware

    def test_clear_session_removes_fields(self):
        session: dict = {
            "authenticated": True,
            "username": "admin",
            "email": "a@b.com",
            "auth_provider": "basic",
            "authenticated_at": "2026-01-01T00:00:00+00:00",
        }
        clear_session(session)
        assert "authenticated" not in session
        assert "username" not in session

    def test_clear_session_preserves_other_keys(self):
        session: dict = {"other_key": "value", "authenticated": True}
        clear_session(session)
        assert session == {"other_key": "value"}


class TestIsAuthEnabled:
    def test_enabled(self):
        cfg = AuthConfig(enabled=True, provider="basic", username="a", password="b")  # noqa: S106
        assert is_auth_enabled(cfg) is True

    def test_disabled(self):
        cfg = AuthConfig(enabled=False)
        assert is_auth_enabled(cfg) is False
