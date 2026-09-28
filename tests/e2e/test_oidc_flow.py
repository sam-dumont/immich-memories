"""The OIDC sign-in, driven in a browser against oidc-provider-mock.

The mock provider and `immich-memories ui` configured for it: the sign-in page's SSO button,
the provider's form, the callback, and the signed-in client with the provider's user name.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import httpx
import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import _build_launch_environment
from tests.e2e.redaction import assert_no_real_address
from tests.e2e.web_flow import evidence, served_ui

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def oidc_mock_server() -> Iterator[int]:
    """Start oidc-provider-mock on a random port."""
    os.environ["AUTHLIB_INSECURE_TRANSPORT"] = "1"
    from oidc_provider_mock import run_server_in_thread

    with run_server_in_thread(port=0) as server:
        port = server.server_port
        httpx.put(
            f"http://localhost:{port}/users/testuser",
            json={
                "preferred_username": "testuser",
                "email": "test@example.com",
                "name": "Test User",
            },
        )
        yield port


@pytest.fixture(scope="module")
def oidc_app_url(
    oidc_mock_server: int, tmp_path_factory, unused_tcp_port_factory, fake_immich_server
) -> Iterator[str]:
    root = tmp_path_factory.mktemp("oidc-auth")
    env = _build_launch_environment(root)
    env["IMMICH_URL"] = fake_immich_server.base_url
    env["IMMICH_API_KEY"] = fake_immich_server.api_key
    env["IMMICH_MEMORIES_AUTH__ENABLED"] = "true"
    env["IMMICH_MEMORIES_AUTH__PROVIDER"] = "oidc"
    env["IMMICH_MEMORIES_AUTH__ISSUER_URL"] = f"http://localhost:{oidc_mock_server}"
    env["IMMICH_MEMORIES_AUTH__CLIENT_ID"] = "test-client"
    env["IMMICH_MEMORIES_AUTH__CLIENT_SECRET"] = "test-secret"  # noqa: S105
    env["IMMICH_MEMORIES_AUTH__ALLOW_INSECURE_ISSUER"] = "true"
    env["AUTHLIB_INSECURE_TRANSPORT"] = "1"
    with served_ui(env, unused_tcp_port_factory(), root / "server.log") as url:
        yield url


def test_oidc_login_flow(oidc_app_url: str, page: Page) -> None:
    """Full OIDC login: SSO button, the provider's form, back to the client signed in."""
    page.goto(oidc_app_url)
    page.wait_for_url("**/app/login")
    sso = page.get_by_role("link", name="Sign in with SSO")
    expect(sso).to_be_visible()
    expect(page.get_by_label("Password")).to_have_count(0)
    assert_no_real_address(page)
    evidence(page, "login-oidc")

    sso.click()
    subject = page.locator('input[name="sub"]')
    expect(subject).to_be_visible(timeout=10_000)
    subject.fill("testuser")
    page.locator('button[type="submit"], input[type="submit"]').first.click()

    page.wait_for_url(f"{oidc_app_url}/app/create", timeout=15_000)
    expect(page.get_by_text("testuser", exact=True)).to_be_visible()
    expect(page.get_by_role("link", name="Sign out")).to_be_visible()
    session = page.request.get(f"{oidc_app_url}/api/v1/session").json()
    assert session["signed_in"] is True
    assert session["username"] == "testuser"
    evidence(page, "oidc-authenticated")
