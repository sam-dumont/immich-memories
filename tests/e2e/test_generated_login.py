"""A server nobody set a login for: it made its own password and printed it once in its log."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import _build_launch_environment
from tests.e2e.web_flow import evidence, served_ui

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def fresh_server(tmp_path_factory, fake_immich_server) -> Iterator[tuple[str, Path]]:
    """A server nobody configured a login for, and the log its first start wrote."""
    root = tmp_path_factory.mktemp("fresh-install")
    env = _build_launch_environment(root)
    env["IMMICH_URL"] = fake_immich_server.base_url
    env["IMMICH_API_KEY"] = fake_immich_server.api_key
    # The harness turns sign-in off for every other test; this one starts it as a user gets it.
    del env["IMMICH_MEMORIES_AUTH__ENABLED"]
    log = root / "server.log"
    with served_ui(env, log) as url:
        yield url, log


@pytest.mark.feature("auth.on-by-default")
def test_a_fresh_server_says_where_its_password_is_and_the_logged_one_signs_in(
    fresh_server: tuple[str, Path], page: Page
) -> None:
    url, log = fresh_server
    page.goto(url)
    page.wait_for_url("**/app/login")
    match = re.search(r"password: (\S+)", log.read_text())
    assert match, "the first start prints the generated password in its log"
    password = match.group(1)
    expect(page.get_by_test_id("generated-login-hint")).to_be_visible()
    expect(page.get_by_text("auth reset-password")).to_be_visible()
    assert password not in page.content()
    evidence(page, "login-generated-password-hint")

    page.get_by_label("Username").fill("admin")
    page.get_by_label("Password").fill(password)
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_url("**/app/create", timeout=10_000)
    expect(page.get_by_role("button", name="Sign out")).to_be_visible()
