"""On a phone (390 px wide) the app is usable on first load, and its header fits."""

from __future__ import annotations

import pytest
from playwright.sync_api import Browser, expect

pytestmark = pytest.mark.e2e

PHONE = {"width": 390, "height": 844}


def test_a_phone_opens_the_app_with_nothing_over_the_page_and_the_header_in_the_screen(
    browser: Browser, launch_app_url: str
) -> None:
    with browser.new_context(viewport=PHONE) as phone:
        page = phone.new_page()
        page.goto(f"{launch_app_url}/app/create", wait_until="domcontentloaded", timeout=30_000)
        brief = page.get_by_text("Monthly Highlights", exact=True)
        expect(brief).to_be_visible(timeout=30_000)

        # The shell's sidebar is an overlay below md: nothing may sit on top of the page.
        on_top = page.evaluate(
            "() => { const e = document.elementFromPoint(innerWidth / 2, innerHeight / 2);"
            " return !!e.closest('main'); }"
        )
        assert on_top, "something covers the middle of the page"
        brief.click()
        expect(page.get_by_label("Month", exact=True)).to_be_visible()

        assert page.evaluate("() => document.documentElement.scrollWidth") <= PHONE["width"]
        toggle = page.locator("header button").last
        box = toggle.bounding_box()
        assert box is not None and box["x"] + box["width"] <= PHONE["width"], box
        # Phones navigate from the bar at the bottom.
        expect(page.get_by_role("navigation", name="Main navigation").last).to_be_visible()
