"""Feature tests for who the served web app lets in, and what it tells a stranger.

Each test starts `immich-memories ui` in a sealed home and talks to it over a socket,
as a browser, a probe or a proxy would. The configured Immich address never answers.
"""

from __future__ import annotations

import base64
import re
from collections.abc import Iterator
from typing import Any

import pytest
import yaml

from immich_memories.web.app import CLIENT_NOT_BUILT
from tests.features.cli_harness import REPO, UserHome, basic_config
from tests.features.oidc_provider import CLIENT_ID, CLIENT_SECRET, OidcProvider
from tests.features.served_app import ServedApp, lan_answer, served_app

UNREACHABLE = "http://127.0.0.1:9"  # discard port: refused at once, no DNS
PASSWORD = "feature-login-password-7c1e"  # noqa: S105 -- throwaway test login
# An app route behind the login that reads only the local store.
PROTECTED = "/api/v1/runs"
DETAIL_FIELDS = ("configuration", "immich_reachable", "immich", "automation", "disk")


def _home(tmp_path, **advanced: Any) -> UserHome:
    home = UserHome(tmp_path / "home")
    config = basic_config(UNREACHABLE, "feature-immich-key", home)
    config["advanced"] |= advanced
    home.write_config(config)
    return home


def _basic_login(username: str = "", password: str = "") -> dict[str, str]:
    """The two variables the shipped Compose `.env` sets to turn the login on."""
    login = {"IMMICH_MEMORIES_AUTH_USERNAME": username, "IMMICH_MEMORIES_AUTH_PASSWORD": password}
    return {name: value for name, value in login.items() if value}


# ── sign-in on by default, on localhost ──────────────────────────────────────


def _logged_password(output: str) -> str:
    """The generated password, from the one log line the first start prints it on."""
    match = re.search(r"password: (\S+)", output)
    assert match, output
    return match.group(1)


@pytest.mark.feature("auth.on-by-default")
def test_a_default_install_asks_for_a_generated_login_and_listens_on_localhost_only(tmp_path):
    home = _home(tmp_path)

    with served_app(home) as app, app.client() as browser:
        session = browser.get("/api/v1/session").json()
        anonymous = browser.get(PROTECTED)
        password = _logged_password(app.output())
        route = browser.get("/api/v1/session/first-login")
        wrong = browser.post("/auth/login", json={"username": "admin", "password": "not-it"})
        right = browser.post("/auth/login", json={"username": "admin", "password": password})
        signed_in = browser.get(PROTECTED)
        lan, reachable_from_lan = lan_answer(app.port)
        output = app.output()

    assert session["auth_enabled"] is True
    assert anonymous.status_code == 401
    assert session["generated_login"] is True
    # Logs only: no route hands the password out.
    assert password not in route.text
    assert wrong.status_code == 401
    assert right.status_code == 200
    assert signed_in.status_code == 200
    assert f"Starting Immich Memories UI on http://127.0.0.1:{app.port}" in output
    assert not reachable_from_lan, f"the default UI answers on {lan}"


@pytest.mark.feature("auth.on-by-default")
def test_turning_the_sign_in_off_opens_the_ui_on_localhost_only(tmp_path):
    home = _home(tmp_path, auth={"enabled": False})

    with served_app(home) as app, app.client() as browser:
        session = browser.get("/api/v1/session").json()
        protected = browser.get(PROTECTED)
        lan, reachable_from_lan = lan_answer(app.port)

    assert session["auth_enabled"] is False
    assert protected.status_code == 200
    assert f"Starting Immich Memories UI on http://127.0.0.1:{app.port}" in app.output()
    assert not reachable_from_lan, f"the UI without sign-in answers on {lan}"


@pytest.mark.feature("auth.on-by-default")
def test_the_shipped_compose_file_publishes_the_ui_on_localhost_only():
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text(encoding="utf-8"))

    published = [port for service in compose["services"].values() for port in service["ports"]]

    assert published, "the shipped Compose file publishes the UI"
    for port in published:
        address = re.fullmatch(r"\$\{UI_BIND_ADDRESS:-([^}]*)\}:\d+:\d+|([^:]+):\d+:\d+", port)
        assert address, f"{port!r} publishes on every address"
        assert (address[1] or address[2]) == "127.0.0.1", port


# ── Basic auth ───────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def basic_app(tmp_path_factory) -> Iterator[ServedApp]:
    """A server whose login is turned on the documented way: the two variables."""
    home = _home(tmp_path_factory.mktemp("basic"))
    with served_app(home, env=_basic_login("admin", PASSWORD)) as app:
        yield app


@pytest.mark.feature("auth.basic")
def test_the_username_and_password_turn_on_the_login_and_a_basic_header_is_refused(basic_app):
    header = base64.b64encode(f"admin:{PASSWORD}".encode()).decode()

    with basic_app.client() as browser:
        anonymous = browser.get(PROTECTED)
        with_header = browser.get(PROTECTED, headers={"Authorization": f"Basic {header}"})
        wrong = browser.post("/auth/login", json={"username": "admin", "password": "not-it"})
        still_out = browser.get(PROTECTED)
        right = browser.post("/auth/login", json={"username": "admin", "password": PASSWORD})
        signed_in = browser.get(PROTECTED)
        page = browser.get("/app/create")

    assert anonymous.status_code == 401
    assert with_header.status_code == 401
    assert wrong.status_code == 401
    assert still_out.status_code == 401
    assert right.status_code == 200
    assert signed_in.status_code == 200
    # Signed in, the UI page is served. A test cell that never built the web client gets the
    # documented "not built" page instead (503); what matters here is that the login let it through.
    assert page.status_code == 200 or (page.status_code == 503 and page.text == CLIENT_NOT_BUILT), (
        page.status_code
    )


@pytest.mark.feature("auth.reset-password")
def test_auth_reset_password_prints_a_new_one_and_signs_every_browser_out(tmp_path):
    home = _home(tmp_path)

    with served_app(home) as app, app.client() as browser:
        old = _logged_password(app.output())
        signed_in = browser.post("/auth/login", json={"username": "admin", "password": old})
        reset = home.run("auth", "reset-password")
        new = re.search(r"password: (\S+)", reset.output)
        signed_out = browser.get(PROTECTED)
        refused = browser.post("/auth/login", json={"username": "admin", "password": old})
        accepted = browser.post(
            "/auth/login", json={"username": "admin", "password": new.group(1) if new else ""}
        )
        logged = app.output()

    assert signed_in.status_code == 200
    assert reset.returncode == 0, reset.explain()
    assert new and new.group(1) != old
    assert new.group(1) not in logged
    assert signed_out.status_code == 401
    assert refused.status_code == 401
    assert accepted.status_code == 200


@pytest.mark.feature("auth.basic")
def test_a_username_alone_does_not_pick_the_name_the_generated_password_goes_with(tmp_path):
    home = _home(tmp_path)

    with served_app(home, env=_basic_login("family")) as app, app.client() as browser:
        password = _logged_password(app.output())
        anonymous = browser.get(PROTECTED)
        renamed = browser.post("/auth/login", json={"username": "family", "password": password})
        right = browser.post("/auth/login", json={"username": "admin", "password": password})

    assert anonymous.status_code == 401
    assert renamed.status_code == 401
    assert right.status_code == 200


# ── health endpoints ─────────────────────────────────────────────────────────


@pytest.mark.feature("web.health-endpoints")
def test_health_answers_a_probe_without_a_session_and_hides_the_detail(basic_app):
    pod_ip = {"Host": "10.0.0.5:8080"}

    with basic_app.client() as probe:
        live = probe.get("/health/live")
        ready = probe.get("/health/ready")
        compatibility = probe.get("/health")
        live_by_pod_ip = probe.get("/health/live", headers=pod_ip)
        ready_by_pod_ip = probe.get("/health/ready", headers=pod_ip)
    with basic_app.client() as browser:
        browser.post("/auth/login", json={"username": "admin", "password": PASSWORD})
        signed_in = browser.get("/health/ready").json()

    assert live.status_code == 200
    assert live.json()["status"] == "alive"
    assert live.json()["version"]
    # The configured Immich never answers: not ready, and still served.
    assert ready.status_code == 503
    assert ready.json()["status"] == "degraded"
    assert ready.json()["version"]
    assert compatibility.status_code == 200
    assert compatibility.json()["status"] == "degraded"
    for body in (ready.json(), compatibility.json()):
        assert {field: body[field] for field in DETAIL_FIELDS} == dict.fromkeys(DETAIL_FIELDS)
    assert live_by_pod_ip.status_code == 200
    assert ready_by_pod_ip.status_code == 503
    assert signed_in["configuration"]
    assert signed_in["immich"]["reachable"] is False


# ── trusted header ───────────────────────────────────────────────────────────


def _header_home(tmp_path, proxy: str) -> UserHome:
    return _home(
        tmp_path,
        auth={"enabled": True, "provider": "header", "trusted_proxies": [proxy]},
    )


@pytest.mark.feature("auth.trusted-header")
def test_the_user_a_trusted_proxy_names_is_signed_in_and_followed(tmp_path):
    # The test itself is the proxy: it connects from the loopback.
    home = _header_home(tmp_path, "127.0.0.1")

    with served_app(home) as app, app.client() as proxy:
        named = proxy.get(PROTECTED, headers={"Remote-User": "proxy-user"})
        who = proxy.get("/api/v1/session").json()["username"]
        switched = proxy.get(PROTECTED, headers={"Remote-User": "other-user"})
        who_now = proxy.get("/api/v1/session").json()["username"]
        unnamed = proxy.get(PROTECTED)

    assert named.status_code == 200
    assert who == "proxy-user"
    assert switched.status_code == 200
    assert who_now == "other-user"
    assert unnamed.status_code == 401


@pytest.mark.feature("auth.trusted-header")
def test_the_header_from_anyone_but_the_trusted_proxy_signs_nobody_in(tmp_path):
    home = _header_home(tmp_path, "192.0.2.10")

    with served_app(home) as app, app.client() as stranger:
        response = stranger.get(PROTECTED, headers={"Remote-User": "proxy-user"})

    assert response.status_code == 401


# ── OIDC ─────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def oidc() -> Iterator[OidcProvider]:
    provider = OidcProvider.start()
    yield provider
    provider.close()


@pytest.fixture(scope="module")
def oidc_app(tmp_path_factory, oidc: OidcProvider) -> Iterator[ServedApp]:
    home = _home(
        tmp_path_factory.mktemp("oidc"),
        auth={
            "enabled": True,
            "provider": "oidc",
            "issuer_url": oidc.issuer,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "allowed_emails": ["owner@family.example"],
            "allowed_domains": ["friends.example"],
        },
    )
    with served_app(home) as app:
        yield app


def _sign_in(app: ServedApp, provider: OidcProvider, email: str, *, verified: bool = True):
    """The whole browser round trip: the app, the provider, the callback, then the app again."""
    browser = app.client()
    authorize = browser.get("/auth/authorize")
    assert authorize.status_code == 302, authorize.text
    callback = browser.get(
        provider.approve(authorize.headers["location"], email=email, verified=verified)
    )
    return browser, authorize, callback, browser.get(PROTECTED)


@pytest.mark.feature("auth.oidc")
@pytest.mark.parametrize(
    "email", ["owner@family.example", "OWNER@family.example", "kid@friends.example"]
)
def test_oidc_signs_in_an_allowed_account_through_the_provider_with_pkce(
    oidc_app, oidc: OidcProvider, email
):
    checks_before = len(oidc.verifier_checks)

    browser, authorize, callback, app_after = _sign_in(oidc_app, oidc, email)
    browser.close()

    assert "code_challenge=" in authorize.headers["location"]
    assert callback.status_code in (302, 303, 307), callback.text
    assert app_after.status_code == 200
    # The provider checked the verifier against the challenge, and it matched.
    assert oidc.verifier_checks[checks_before:] == [True]


@pytest.mark.feature("auth.oidc")
@pytest.mark.parametrize(
    ("email", "verified"),
    [
        ("stranger@elsewhere.example", True),
        ("kid@sub.friends.example", True),
        ("owner@family.example", False),
    ],
)
def test_oidc_refuses_an_account_off_the_allow_list(oidc_app, oidc: OidcProvider, email, verified):
    browser, _, callback, app_after = _sign_in(oidc_app, oidc, email, verified=verified)
    browser.close()

    assert callback.status_code == 403
    assert "Not authorised" in callback.text
    assert app_after.status_code == 401


# ── allowed hosts and writes from other sites ────────────────────────────────


@pytest.mark.feature("web.allowed-hosts")
def test_the_server_answers_only_the_hosts_it_was_told_to_accept(tmp_path):
    home = _home(tmp_path, auth={"enabled": False}, server={"allowed_hosts": ["nas.lan"]})

    with served_app(home) as app, app.client() as browser:
        statuses = {
            host: browser.get(PROTECTED, headers={"Host": host}).status_code
            for host in ("localhost:8080", "127.0.0.1", "[::1]:8080", "nas.lan:8080", "NAS.lan")
        }
        rebound = browser.get(PROTECTED, headers={"Host": "rebind.attacker.example"})
        rebound_page = browser.get("/app/create", headers={"Host": "rebind.attacker.example"})

    assert set(statuses.values()) == {200}, statuses
    assert rebound.status_code == 421
    assert "feature-immich-key" not in rebound.text
    assert rebound_page.status_code == 421


@pytest.mark.feature("web.allowed-hosts")
def test_a_write_from_another_site_is_refused_and_changes_nothing(tmp_path):
    home = _home(tmp_path, auth={"enabled": False})
    cached = (
        home.root / ".immich-memories" / "cache" / "thumbnails" / "ab" / "ab-picture_preview.jpg"
    )
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"\xff\xd8 a cached preview")
    clear = "/api/v1/caches/thumbnail/clear"

    with served_app(home) as app, app.client() as browser:
        from_a_page = browser.post(clear, headers={"Origin": "https://evil.example"})
        marked_cross_site = browser.post(clear, headers={"Sec-Fetch-Site": "cross-site"})
        survived = cached.exists()
        from_this_origin = browser.post(clear, headers={"Origin": app.url})

    assert (from_a_page.status_code, marked_cross_site.status_code) == (403, 403)
    assert survived
    assert from_this_origin.status_code == 200
    assert not cached.exists()
