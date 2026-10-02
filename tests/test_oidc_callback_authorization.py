"""An email allow-list must not trust an unverified profile address."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from immich_memories.config_loader import Config
from immich_memories.config_models_auth import AuthConfig
from tests.web_server_fixtures import SESSION_SECRET


@pytest.mark.parametrize("verified", [False, None, "true", 1, True])
@pytest.mark.parametrize(
    "allow_list", [{"allowed_emails": ["owner@example.com"]}, {"allowed_domains": ["example.com"]}]
)
def test_callback_checks_email_ownership_before_creating_a_session(
    monkeypatch, verified, allow_list
):
    from immich_memories.web import server as web_server

    config = Config(
        auth=AuthConfig(
            enabled=True,
            provider="oidc",
            issuer_url="https://idp.example.com",
            client_id="memories",
            **allow_list,
        )
    )
    # WHY: the IdP exchange and browser session are external login boundaries.
    oauth = SimpleNamespace(
        oidc=SimpleNamespace(
            authorize_access_token=AsyncMock(
                return_value={
                    "userinfo": {
                        "sub": "different-account",
                        "email": "owner@example.com",
                        "email_verified": verified,
                    }
                }
            )
        )
    )
    monkeypatch.setattr(web_server, "get_config", lambda: config)
    monkeypatch.setattr("immich_memories.web.auth_oidc.create_oidc_client", lambda _config: oauth)
    server = FastAPI()
    server.state.session_secret = SESSION_SECRET
    server.add_api_route("/auth/callback", web_server.oidc_callback, methods=["GET"])

    async def whoami(request: Request) -> dict:
        return dict(request.session)

    server.add_api_route("/whoami", whoami, methods=["GET"])
    server.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)  # noqa: S106

    with TestClient(server) as client:
        response = client.get("/auth/callback", follow_redirects=False)
        session = client.get("/whoami").json()

    assert response.status_code == (307 if verified is True else 403)
    assert bool(session.get("authenticated")) is (verified is True)


@pytest.mark.parametrize(
    "query",
    [
        "code=unused&state=stale",
        "code=unused",
        "error=access_denied&error_description=private-detail",
    ],
)
def test_expired_callback_returns_to_sign_in_without_a_traceback(monkeypatch, caplog, query):
    from immich_memories.web import auth_oidc
    from immich_memories.web import server as web_server

    config = Config(
        auth=AuthConfig(
            enabled=True,
            provider="oidc",
            issuer_url="https://idp.example.com",
            client_id="memories",
        )
    )
    # WHY: configuration is external; Authlib handles the real missing browser state.
    monkeypatch.setattr(web_server, "get_config", lambda: config)
    auth_oidc.reset_oidc_client()
    server = FastAPI()
    server.state.session_secret = SESSION_SECRET
    server.add_api_route("/auth/callback", web_server.oidc_callback, methods=["GET"])
    server.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)  # noqa: S106
    try:
        with TestClient(server, raise_server_exceptions=False) as client:
            response = client.get(f"/auth/callback?{query}", follow_redirects=False)
    finally:
        auth_oidc.reset_oidc_client()

    assert response.status_code == 303
    assert response.headers["location"] == "/app/login?error=signin_expired"
    warnings = [record for record in caplog.records if record.levelname == "WARNING"]
    assert len(warnings) == 1
    assert warnings[0].getMessage() == "OIDC sign-in expired or was refused; retry sign-in"
    assert warnings[0].exc_info is None
    assert "private-detail" not in warnings[0].getMessage()
