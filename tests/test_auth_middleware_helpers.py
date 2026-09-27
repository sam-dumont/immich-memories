"""The server's sign-in helpers: header auth from a trusted proxy, and the session's lifetime."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from starlette.requests import Request

from immich_memories.config_loader import Config
from immich_memories.config_models_auth import AuthConfig
from immich_memories.web.server import _auth_middleware, _expired, _try_header_auth


def _request(
    host: str = "10.0.0.1",
    path: str = "/",
    headers: dict[str, str] | None = None,
    session: dict[str, Any] | None = None,
) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "query_string": b"",
            "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
            "server": ("localhost", 8080),
            "client": (host, 12345),
            "session": {} if session is None else session,
        }
    )


def _header_auth() -> AuthConfig:
    return AuthConfig(
        enabled=True,
        provider="header",
        trusted_proxies=["10.0.0.0/8"],
        user_header="X-User",
        email_header="X-Email",
    )


class TestTryHeaderAuth:
    def test_trusted_proxy_creates_session(self):
        request = _request(headers={"X-User": "test-operator", "X-Email": "a@b.com"})

        _try_header_auth(request, _header_auth())

        assert request.session["authenticated"] is True
        assert request.session["username"] == "test-operator"
        assert request.session["email"] == "a@b.com"
        assert request.session["auth_provider"] == "header"

    def test_untrusted_proxy_does_nothing(self):
        request = _request(host="192.168.1.1", headers={"X-User": "test-operator"})

        _try_header_auth(request, _header_auth())

        assert request.session == {}

    def test_already_authenticated_keeps_the_session(self):
        session = {"authenticated": True, "username": "bob"}
        request = _request(headers={"X-User": "test-operator"}, session=session)

        _try_header_auth(request, _header_auth())

        assert request.session["username"] == "bob"

    def test_no_user_header_skips_session(self):
        request = _request()

        _try_header_auth(request, _header_auth())

        assert request.session == {}


class TestSessionLifetime:
    def test_no_authenticated_at_never_expires(self):
        assert _expired({}, 24) is False

    def test_fresh_session_is_live(self):
        assert _expired({"authenticated_at": datetime.now(UTC).isoformat()}, 24) is False

    def test_old_session_is_expired(self):
        started = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
        assert _expired({"authenticated_at": started}, 24) is True

    @pytest.mark.asyncio
    async def test_an_expired_session_is_cleared_and_sent_to_sign_in(self, monkeypatch):
        config = Config(
            auth={"enabled": True, "provider": "basic", "username": "a", "password": "b"}
        )
        # WHY: the config file is the boundary; the test states the auth it needs.
        monkeypatch.setattr("immich_memories.web.server.get_config", lambda: config)
        session = {
            "authenticated": True,
            "username": "a",
            "authenticated_at": (datetime.now(UTC) - timedelta(hours=25)).isoformat(),
        }
        request = _request(path="/app/runs", session=session)

        async def call_next(_request):
            raise AssertionError("an expired session reached the page")

        response = await _auth_middleware(request, call_next)

        assert response.status_code == 307
        assert "authenticated" not in session
