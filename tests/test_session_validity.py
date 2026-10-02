"""A session cookie stands only while its sign-in does: sign-out, rule changes and age end it."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from immich_memories.config_loader import Config
from immich_memories.web.auth import reset_rate_limiter
from tests.web_server_fixtures import basic_auth_config, server_client, signed_session

_PROXY = "10.0.0.2"


@pytest.fixture(autouse=True)
def _fresh_limiter():
    reset_rate_limiter()
    yield
    reset_rate_limiter()


def _signed_in(monkeypatch: pytest.MonkeyPatch, config: Config):
    client = server_client(monkeypatch, config)
    response = client.post(
        "/auth/login", json={"username": config.auth.username, "password": config.auth.password}
    )
    assert response.status_code == 200
    return client


def _with_cookie(monkeypatch: pytest.MonkeyPatch, config: Config, cookie: str):
    client = server_client(monkeypatch, config)
    client.cookies.set("session", cookie)
    return client


def test_a_cookie_kept_from_before_sign_out_is_refused_after_it(monkeypatch):
    config = basic_auth_config()
    client = _signed_in(monkeypatch, config)
    kept = client.cookies.get("session")
    assert _with_cookie(monkeypatch, config, kept).get("/api/v1/connection").status_code == 200

    client.post("/logout")

    assert _with_cookie(monkeypatch, config, kept).get("/api/v1/connection").status_code == 401


def test_signing_out_ends_only_that_users_sessions(monkeypatch):
    config = basic_auth_config()
    someone_else = signed_session(config, username="someone-else")

    _signed_in(monkeypatch, config).post("/logout")

    replay = _with_cookie(monkeypatch, config, someone_else)
    assert replay.get("/api/v1/connection").status_code == 200


def test_signing_in_again_after_sign_out_works(monkeypatch):
    config = basic_auth_config()
    _signed_in(monkeypatch, config).post("/logout")

    assert _signed_in(monkeypatch, config).get("/api/v1/connection").status_code == 200


def test_a_password_change_ends_every_session(monkeypatch):
    before = basic_auth_config()
    kept = _signed_in(monkeypatch, before).cookies.get("session")
    after = Config(auth={**before.auth.model_dump(), "password": "a-new-password-entirely"})

    assert _with_cookie(monkeypatch, after, kept).get("/api/v1/connection").status_code == 401


def test_a_provider_change_ends_every_session(monkeypatch):
    before = basic_auth_config()
    kept = _signed_in(monkeypatch, before).cookies.get("session")
    after = Config(
        auth={
            "enabled": True,
            "provider": "oidc",
            "issuer_url": "https://id.example",
            "client_id": "c",
        }
    )

    assert _with_cookie(monkeypatch, after, kept).get("/api/v1/connection").status_code == 401


def test_a_cookie_without_the_current_stamps_is_refused(monkeypatch):
    config = basic_auth_config()
    unstamped = signed_session(config, auth_fingerprint="", session_generation=None)

    assert _with_cookie(monkeypatch, config, unstamped).get("/api/v1/connection").status_code == 401


def test_the_session_view_reports_a_stale_cookie_as_signed_out(monkeypatch):
    config = basic_auth_config()
    stale = signed_session(config, auth_fingerprint="stale")

    assert (
        _with_cookie(monkeypatch, config, stale).get("/api/v1/session").json()["signed_in"] is False
    )


def _header_config() -> Config:
    return Config(auth={"enabled": True, "provider": "header", "trusted_proxies": [_PROXY]})


def test_header_auth_follows_the_user_the_proxy_names_on_each_request(monkeypatch):
    client = server_client(monkeypatch, _header_config(), client=(_PROXY, 40000))

    assert client.get("/api/v1/connection", headers={"Remote-User": "ada"}).status_code == 200
    assert client.get("/api/v1/connection", headers={"Remote-User": "bob"}).status_code == 200

    assert client.get("/api/v1/session").json()["username"] == "bob"


def test_header_auth_without_the_header_is_not_signed_in(monkeypatch):
    client = server_client(monkeypatch, _header_config(), client=(_PROXY, 40000))
    assert client.get("/api/v1/connection", headers={"Remote-User": "ada"}).status_code == 200

    assert client.get("/api/v1/connection").status_code == 401


def test_header_auth_ignores_the_header_from_an_untrusted_peer(monkeypatch):
    client = server_client(monkeypatch, _header_config(), client=("192.0.2.9", 40000))

    assert client.get("/api/v1/connection", headers={"Remote-User": "ada"}).status_code == 401


def test_an_expired_session_is_sent_to_sign_in(monkeypatch):
    config = basic_auth_config()
    old = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
    client = _with_cookie(monkeypatch, config, signed_session(config, authenticated_at=old))

    response = client.get("/app/runs")

    assert response.status_code == 307
    assert response.headers["location"] == "/app/login"


def _health(monkeypatch: pytest.MonkeyPatch, cookie: str) -> dict:
    from immich_memories.web import health

    # WHY: the snapshot is cached across requests; each test builds its own.
    monkeypatch.setattr(health, "_health_snapshot_cache", None)
    return _with_cookie(monkeypatch, basic_auth_config(), cookie).get("/health").json()


def test_health_detail_goes_to_a_current_session(monkeypatch):
    body = _health(monkeypatch, signed_session(basic_auth_config()))

    assert body["in_process_scheduler"] is not None


def test_health_detail_is_withheld_from_an_expired_session(monkeypatch):
    old = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
    body = _health(monkeypatch, signed_session(basic_auth_config(), authenticated_at=old))

    assert body["in_process_scheduler"] is None
    assert body["status"]


def test_get_logout_does_not_end_a_session(monkeypatch):
    client = _signed_in(monkeypatch, basic_auth_config())

    assert client.get("/logout").status_code == 405
    assert client.get("/api/v1/connection").status_code == 200


def test_post_logout_redirects_to_login_with_get(monkeypatch):
    client = _signed_in(monkeypatch, basic_auth_config())

    response = client.post("/logout", headers={"Origin": str(client.base_url).rstrip("/")})

    assert response.status_code == 303
    assert response.headers["location"] == "/app/login"
    assert client.get("/api/v1/connection").status_code == 401


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://foreign.example"},
        {"Origin": "null"},
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "same-site"},
    ],
)
def test_cross_site_logout_does_not_end_a_session(monkeypatch, headers):
    client = _signed_in(monkeypatch, basic_auth_config())

    assert client.post("/logout", headers=headers).status_code == 403
    assert client.get("/api/v1/connection").status_code == 200


def test_oidc_logout_redirects_to_provider_with_get(monkeypatch):
    config = Config(
        auth={
            "enabled": True,
            "provider": "oidc",
            "issuer_url": "https://id.example",
            "client_id": "client",
        }
    )
    client = _with_cookie(monkeypatch, config, signed_session(config))
    # WHY: the provider metadata is an external HTTP boundary.
    monkeypatch.setattr(
        "immich_memories.web.auth_oidc.get_end_session_url",
        lambda _auth: "https://id.example/logout",
    )

    response = client.post("/logout")

    assert response.status_code == 303
    assert response.headers["location"] == "https://id.example/logout"
    assert client.get("/api/v1/connection").status_code == 401
