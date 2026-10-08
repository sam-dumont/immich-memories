"""The security review's regression tests: each fix stays fixed.

Every test here is an inverted probe from the review that found the bug it guards
against; the probes lived in `/private/tmp` while the bugs reproduced, and moved
here asserting the fixed behaviour when they were fixed.
"""

from __future__ import annotations

import json

import pytest

from immich_memories.config_loader import Config
from tests.web_server_fixtures import basic_auth_config, server_client, signed_session


@pytest.fixture(autouse=True)
def _fresh_limiter():
    from immich_memories.web.auth import reset_rate_limiter

    reset_rate_limiter()
    yield
    reset_rate_limiter()


@pytest.fixture(autouse=True)
def _fresh_oidc_client():
    from immich_memories.web.auth_oidc import reset_oidc_client

    reset_oidc_client()
    yield
    reset_oidc_client()


def _oidc_config(
    issuer: str,
    client_id: str = "client",
    secret: str = "secret",  # noqa: S107 — synthetic
) -> Config:
    return Config(
        auth={
            "enabled": True,
            "provider": "oidc",
            "issuer_url": issuer,
            "client_id": client_id,
            "client_secret": secret,
        }
    )


# 3. A body past the default cap is refused before it is buffered, pre-auth.
def test_an_oversized_login_body_is_refused_up_front(monkeypatch):
    client = server_client(monkeypatch, basic_auth_config())
    password = "x" * (8 * 1024 * 1024)
    response = client.post(
        "/auth/login",
        content=json.dumps({"username": "operator", "password": password}),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413
    assert b"too large" in response.content.lower()


def test_a_small_login_body_still_reaches_the_credential_check(monkeypatch):
    config = basic_auth_config()
    client = server_client(monkeypatch, config)
    ok = client.post("/auth/login", json={"username": "operator", "password": "test-password"})
    wrong = client.post("/auth/login", json={"username": "operator", "password": "nope"})
    assert ok.status_code == 200
    assert wrong.status_code == 401


# 4. The cached OIDC client follows the registration it was built from.
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("issuer_url", "https://second.example"),
        ("client_id", "another-client"),
        ("client_secret", "rotated-secret"),
        ("scope", "openid email"),
    ],
)
def test_a_changed_oidc_registration_rebuilds_the_client(field, value):
    from immich_memories.web.auth_oidc import create_oidc_client

    first = create_oidc_client(_oidc_config("https://first.example").auth)
    again = create_oidc_client(_oidc_config("https://first.example").auth)
    assert first is again, "an unchanged registration keeps the client (authlib keeps PKCE state)"

    changed = _oidc_config("https://first.example").auth
    setattr(changed, field, value)
    rebuilt = create_oidc_client(changed)
    assert rebuilt is not first
    registration = rebuilt.oidc
    actual = {
        "issuer_url": registration._server_metadata_url.removesuffix(
            "/.well-known/openid-configuration"
        ),
        "client_id": registration.client_id,
        "client_secret": registration.client_secret,
        "scope": registration.client_kwargs["scope"],
    }
    assert actual[field] == value


# 6. A hostile asset id never reaches the caches' filesystem paths.
def test_a_hostile_asset_id_is_refused_at_the_parse():
    from pydantic import ValidationError

    from immich_memories.api.models import Asset

    with pytest.raises(ValidationError):
        Asset(
            id="../../escaped",
            type="VIDEO",
            original_file_name="evil.sh",
            file_created_at="2026-01-01T00:00:00Z",
            file_modified_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )


def test_the_video_cache_refuses_a_path_that_would_escape(tmp_path):
    from immich_memories.cache.video_cache import VideoDownloadCache

    cache = VideoDownloadCache(tmp_path / "cache")
    with pytest.raises(ValueError):
        cache._video_path("../../escaped", ".sh")


def test_the_thumbnail_cache_refuses_a_path_that_would_escape(tmp_path):
    from immich_memories.cache.thumbnail_cache import ThumbnailCache

    cache = ThumbnailCache(tmp_path / "cache")
    with pytest.raises(ValueError):
        cache._path("../../escaped", "preview")


# 7. An unauthenticated probe gets status and version only from the health routes.
def test_health_tells_a_probe_nothing_but_status_and_version(monkeypatch):
    config = basic_auth_config()
    client = server_client(monkeypatch, config)
    body = client.get("/health").json()
    assert body["status"] in ("ok", "degraded")
    assert body["version"]
    for field in ("immich", "immich_reachable", "configuration", "automation", "disk"):
        assert body[field] is None, f"{field} is deployment detail, not liveness"


def test_health_keeps_its_detail_for_a_current_session(monkeypatch):
    config = basic_auth_config()
    client = server_client(monkeypatch, config)
    client.cookies.set("session", signed_session(config))
    body = client.get("/health").json()
    assert body["configuration"]
    assert isinstance(body["immich"], dict)


# 8. Sign-in lockouts only count attempts that actually tried a credential.
def test_junk_logins_against_an_oidc_server_pause_nothing(monkeypatch):
    client = server_client(monkeypatch, _oidc_config("https://id.example"))
    statuses = [
        client.post("/auth/login", json={"username": f"user-{i}", "password": "x"}).status_code
        for i in range(12)
    ]
    assert set(statuses) == {401}, "no credential was attempted, so none failed"


def test_wrong_passwords_on_a_basic_server_still_lock_out(monkeypatch):
    from immich_memories.web.auth import _MAX_ATTEMPTS

    client = server_client(monkeypatch, basic_auth_config())
    statuses = [
        client.post("/auth/login", json={"username": "operator", "password": "x"}).status_code
        for _ in range(_MAX_ATTEMPTS + 1)
    ]
    assert statuses[-1] == 429, "real failed credentials still engage the limiter"


# 9. Credentials embedded in the Immich URL are refused at load; errors name no userinfo.
def test_userinfo_in_the_immich_url_is_refused():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Config(immich={"url": "https://me:hunter2@immich.example.com", "api_key": "k"})


def test_transport_errors_name_the_host_not_the_credentials():
    import httpx

    from immich_memories.api.immich import ImmichClient

    client = ImmichClient(base_url="https://me:hunter2@immich.example.com", api_key="synthetic-key")
    error = client._request_error(httpx.ConnectError("boom"))
    assert "immich.example.com" in str(error)
    assert "hunter2" not in str(error)
    assert "me:" not in str(error)


# 12. With a public URL named, a foreign Host is refused even with no allow-list.
def test_a_public_url_pins_the_host_when_auth_is_on(monkeypatch):
    from immich_memories.web import request_checks

    config = basic_auth_config()
    config.auth.public_url = "https://memories.example.com"
    assert request_checks.host_allowed("memories.example.com", config)
    assert not request_checks.host_allowed("evil.example", config), (
        "the sign-in redirect trusts the public URL, so another host is not answered"
    )


def test_without_a_public_url_or_allow_list_any_host_is_answered(monkeypatch):
    from immich_memories.web import request_checks

    config = basic_auth_config()
    assert request_checks.host_allowed("evil.example", config)


# 13. A page on another site cannot start discovery behind a navigation.
def test_a_cross_site_refresh_is_ignored(monkeypatch):
    from immich_memories.web.request_origin import cross_site_request

    config = basic_auth_config()
    headers = {"sec-fetch-site": "cross-site", "host": "app.local"}
    assert cross_site_request(headers, config)


# 15. A hostile upstream content-type never becomes this app's own.
def test_the_playback_route_clamps_a_hostile_content_type(monkeypatch):
    from immich_memories.web.dependencies import Playback, immich_playback

    config = basic_auth_config()
    config.immich.url = "https://primary.example"
    config.immich.api_key = "primary-synthetic-key"
    client = server_client(monkeypatch, config)
    client.cookies.set("session", signed_session(config))

    def hostile_opener():
        def open_playback(asset_id, account, byte_range):
            return Playback(
                status=200,
                headers={"content-type": "text/html; charset=utf-8"},
                chunks=iter([b"<script>alert(document.domain)</script>"]),
            )

        return open_playback

    client.app.dependency_overrides[immich_playback] = hostile_opener
    response = client.get("/api/v1/assets/some-asset/video")
    assert response.status_code == 200
    assert response.headers["content-type"] == "video/mp4"


def test_a_real_video_content_type_is_kept(monkeypatch):
    from immich_memories.web.media import _video_media_type

    assert _video_media_type("video/quicktime") == "video/quicktime"
    assert _video_media_type("video/mp4; charset=utf-8") == "video/mp4; charset=utf-8"
    assert _video_media_type("text/html") == "video/mp4"
    assert _video_media_type(None) == "video/mp4"


# 16. The CSP is a full policy, and it permits exactly the client's inline scripts.
def test_every_response_carries_a_full_content_security_policy(monkeypatch):
    client = server_client(monkeypatch, basic_auth_config())
    policy = client.get("/api/v1/session").headers["content-security-policy"]
    for directive in (
        "default-src 'self'",
        "script-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "connect-src 'self'",
        "frame-ancestors 'none'",
    ):
        assert directive in policy, f"a full policy carries {directive}"


def test_the_csp_permits_exactly_the_built_clients_inline_scripts(monkeypatch):
    import base64
    import hashlib
    import re
    from pathlib import Path

    from immich_memories.web import request_checks

    client_index = Path(request_checks.__file__).parent / "client" / "index.html"
    if not client_index.exists():
        pytest.skip("the web client is not built in this checkout")
    inline = re.findall(r"<script>(.*?)</script>", client_index.read_text(), re.S)
    assert inline, "the built client needs a startup script"
    client = server_client(monkeypatch, basic_auth_config())
    policy = client.get("/api/v1/session").headers["content-security-policy"]
    allowed = {
        base64.b64decode(encoded, validate=True)
        for encoded in re.findall(r"'sha256-([^']+)'", policy)
    }
    assert allowed == {hashlib.sha256(script.encode()).digest() for script in inline}
    script_policy = next(part for part in policy.split(";") if "script-src" in part)
    assert "'unsafe-inline'" not in script_policy


# F1's companion: the HTTP logout route still ends sessions under the new table.
def test_post_logout_still_ends_the_session(monkeypatch):
    config = basic_auth_config()
    client = server_client(monkeypatch, config)
    client.cookies.set("session", signed_session(config))
    assert client.get("/api/v1/connection").status_code == 200

    client.post("/logout")

    assert client.get("/api/v1/connection").status_code == 401
