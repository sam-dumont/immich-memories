"""Basic sign-in, the header's auth controls, demo mode, sign-out, and media behind the session.

The server is `immich-memories ui` itself with basic auth on, on a port of its own.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

import httpx
import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import _build_launch_environment
from tests.e2e.fake_library import CARRIERS
from tests.e2e.redaction import assert_no_real_address
from tests.e2e.web_flow import evidence, served_ui

pytestmark = pytest.mark.e2e

_TEST_USER = "testuser"
_TEST_PASS = "testpass123"  # noqa: S105
_DEMO = re.compile(r"\bdemo-mode\b")


@pytest.fixture(scope="module")
def auth_server_url(tmp_path_factory, unused_tcp_port_factory, fake_immich_server) -> Iterator[str]:
    root = tmp_path_factory.mktemp("basic-auth")
    env = _build_launch_environment(root)
    env["IMMICH_URL"] = fake_immich_server.base_url
    env["IMMICH_API_KEY"] = fake_immich_server.api_key
    env["IMMICH_MEMORIES_AUTH__ENABLED"] = "true"
    env["IMMICH_MEMORIES_AUTH__PROVIDER"] = "basic"
    env["IMMICH_MEMORIES_AUTH__USERNAME"] = _TEST_USER
    env["IMMICH_MEMORIES_AUTH__PASSWORD"] = _TEST_PASS
    with served_ui(env, unused_tcp_port_factory(), root / "server.log") as url:
        yield url


def _sign_in(page: Page, url: str) -> None:
    page.goto(url)
    page.wait_for_url("**/app/login")
    page.get_by_label("Username").fill(_TEST_USER)
    page.get_by_label("Password").fill(_TEST_PASS)
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_url("**/app/create", timeout=10_000)


def test_login_and_auth_controls(auth_server_url: str, page: Page) -> None:
    page.goto(auth_server_url)
    page.wait_for_url("**/app/login")
    expect(page.get_by_role("button", name="Sign in")).to_be_visible()
    assert_no_real_address(page)
    evidence(page, "login-basic-auth")

    page.get_by_label("Username").fill(_TEST_USER)
    page.get_by_label("Password").fill("wrong")
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_role("alert")).to_have_text("Invalid username or password")

    page.get_by_label("Password").fill(_TEST_PASS)
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_url("**/app/create", timeout=10_000)

    expect(page.get_by_text(_TEST_USER, exact=True)).to_be_visible()
    expect(page.get_by_role("link", name="Sign out")).to_be_visible()
    assert_no_real_address(page)
    evidence(page, "memory-with-auth")


def test_demo_mode_toggle_blurs_pictures_and_is_kept_by_this_browser(
    auth_server_url: str, page: Page
) -> None:
    _sign_in(page, auth_server_url)
    toggle = page.get_by_role("button", name="Demo mode")
    body = page.locator("body")
    expect(toggle).to_have_attribute("aria-pressed", "false")
    expect(body).not_to_have_class(_DEMO)

    toggle.click()
    expect(body).to_have_class(_DEMO)
    expect(toggle).to_have_attribute("aria-pressed", "true")
    blur = page.evaluate(
        "() => { const img = document.body.appendChild(document.createElement('img'));"
        " return getComputedStyle(img).filter; }"
    )
    assert "blur" in blur

    page.reload()
    expect(body).to_have_class(_DEMO)
    page.get_by_role("button", name="Demo mode").click()
    expect(body).not_to_have_class(_DEMO)


def test_sign_out(auth_server_url: str, page: Page) -> None:
    _sign_in(page, auth_server_url)

    page.get_by_role("link", name="Sign out").click()
    page.wait_for_url("**/app/login")
    expect(page.get_by_role("button", name="Sign in")).to_be_visible()

    page.goto(f"{auth_server_url}/app/runs")
    page.wait_for_url("**/app/login")
    assert page.request.get(f"{auth_server_url}/api/v1/session").json()["signed_in"] is False


def test_pictures_are_behind_the_login(auth_server_url: str) -> None:
    """A thumbnail without a session is refused with a status, not handed out or redirected."""
    thumbnail = f"/api/v1/assets/{CARRIERS[0].asset_id}/thumbnail"
    with httpx.Client(base_url=auth_server_url) as client:
        refused = client.get(thumbnail, follow_redirects=False)
        signed_in = client.post(
            "/auth/login", json={"username": _TEST_USER, "password": _TEST_PASS}
        )
        picture = client.get(thumbnail)

    assert refused.status_code == 401
    assert signed_in.status_code == 200
    assert picture.status_code == 200
    assert picture.headers["content-type"] == "image/jpeg"
