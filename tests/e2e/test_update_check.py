"""Settings → Updates: the button asks on demand, and the daily banner can be dismissed.

GitHub is never reached from the browser tests: the page's own requests to the app's update
routes are answered here, so the launched app makes no outside call either.
"""

from __future__ import annotations

import json

import pytest
from playwright.sync_api import Page, Route, expect

pytestmark = pytest.mark.e2e

_AVAILABLE = {
    "status": "available",
    "running": "1.0.0",
    "latest": "1.0.1",
    "notes_url": "https://github.com/sam-dumont/immich-memories/releases/tag/v1.0.1",
    "command": "docker compose pull && docker compose up -d",
    "install_method": "docker",
    "docs_url": "https://sam-dumont.github.io/immich-memories/docs/run/maintenance/upgrading",
    "reason": None,
}


def _answer(body: object, hits: list[str] | None = None):
    def handler(route: Route) -> None:
        if hits is not None:
            hits.append(route.request.url)
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    return handler


@pytest.mark.feature("updates.check")
def test_the_button_checks_only_when_clicked_and_shows_the_command(
    page: Page, launch_app_url: str
) -> None:
    hits: list[str] = []
    page.route("**/api/v1/updates", _answer(_AVAILABLE, hits))
    page.route("**/api/v1/updates/daily", _answer(None))
    page.goto(f"{launch_app_url}/app/settings", wait_until="domcontentloaded", timeout=30_000)

    button = page.get_by_role("button", name="Check for updates")
    expect(button).to_be_visible(timeout=30_000)
    assert hits == []

    button.click()

    result = page.get_by_test_id("update-result")
    expect(result).to_contain_text("1.0.1 is out")
    expect(result).to_contain_text("docker compose pull && docker compose up -d")
    expect(result.get_by_role("link", name="Release notes")).to_have_attribute(
        "href", _AVAILABLE["notes_url"]
    )
    assert len(hits) == 1


def test_an_up_to_date_install_and_a_failed_check_each_say_so(
    page: Page, launch_app_url: str
) -> None:
    page.route("**/api/v1/updates/daily", _answer(None))
    page.route("**/api/v1/updates", _answer({**_AVAILABLE, "status": "current", "latest": None}))
    page.goto(f"{launch_app_url}/app/settings", wait_until="domcontentloaded", timeout=30_000)
    page.get_by_role("button", name="Check for updates").click()
    expect(page.get_by_test_id("update-result")).to_contain_text("You're up to date.")

    page.unroute("**/api/v1/updates")
    page.route(
        "**/api/v1/updates",
        _answer({**_AVAILABLE, "status": "failed", "reason": "could not reach GitHub (timeout)"}),
    )
    page.get_by_role("button", name="Check for updates").click()
    expect(page.get_by_test_id("update-result")).to_contain_text("Could not check for updates")


@pytest.mark.feature("updates.daily")
def test_the_daily_banner_shows_a_new_release_and_stays_dismissed(
    page: Page, launch_app_url: str
) -> None:
    page.route("**/api/v1/updates/daily", _answer(_AVAILABLE))
    page.goto(f"{launch_app_url}/app/settings", wait_until="domcontentloaded", timeout=30_000)

    banner = page.get_by_test_id("update-banner")
    expect(banner).to_contain_text("1.0.1 is out", timeout=30_000)

    banner.get_by_role("button", name="Dismiss").click()
    expect(banner).to_have_count(0)

    page.reload(wait_until="domcontentloaded")
    expect(page.get_by_role("button", name="Check for updates")).to_be_visible(timeout=30_000)
    expect(page.get_by_test_id("update-banner")).to_have_count(0)


def test_no_banner_when_the_daily_check_is_off(page: Page, launch_app_url: str) -> None:
    page.route("**/api/v1/updates/daily", _answer(None))
    page.goto(f"{launch_app_url}/app/settings", wait_until="domcontentloaded", timeout=30_000)
    expect(page.get_by_role("button", name="Check for updates")).to_be_visible(timeout=30_000)
    expect(page.get_by_test_id("update-banner")).to_have_count(0)
