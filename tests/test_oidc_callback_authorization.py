"""An email allow-list must not trust an unverified profile address."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from immich_memories.config_models_auth import AuthConfig


@pytest.mark.parametrize("verified", [False, None, "true", 1, True])
@pytest.mark.parametrize(
    "allow_list", [{"allowed_emails": ["owner@example.com"]}, {"allowed_domains": ["example.com"]}]
)
def test_callback_checks_email_ownership_before_creating_a_session(
    monkeypatch, verified, allow_list
):
    from immich_memories.web import server as web_server

    config = SimpleNamespace(
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
    server.add_api_route("/auth/callback", web_server.oidc_callback, methods=["GET"])

    async def whoami(request: Request) -> dict:
        return dict(request.session)

    server.add_api_route("/whoami", whoami, methods=["GET"])
    server.add_middleware(SessionMiddleware, secret_key="test-secret")  # noqa: S106

    with TestClient(server) as client:
        response = client.get("/auth/callback", follow_redirects=False)
        session = client.get("/whoami").json()

    assert response.status_code == (307 if verified is True else 403)
    assert bool(session.get("authenticated")) is (verified is True)
