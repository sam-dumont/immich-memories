"""A person spotlight's pool shows the pictures the person's episodes bring, marked.

The fixture library names people only on the first picture of each scene; the other
views of the same scene were taken minutes later and name nobody. A spotlight on one
person must still offer those views on the review screen, marked "Same episode", so
the owner can untick them before the cut.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.test_launch_smoke import _choose

pytestmark = pytest.mark.e2e


def test_a_spotlight_pool_offers_and_marks_the_pictures_of_the_persons_episodes(
    page: Page, launch_app_url: str
) -> None:
    page.goto(launch_app_url, wait_until="domcontentloaded", timeout=30_000)
    expect(page.get_by_role("combobox", name="Memory type")).to_be_visible(timeout=30_000)
    _choose(page, "Memory type", "Person Spotlight")
    _choose(page, "Year", "2024")
    _choose(page, "Person", "Kit")
    page.get_by_role("button", name="Cut", exact=True).click()

    review = page.get_by_role("button", name="Review the pool", exact=True)
    expect(review).to_be_visible(timeout=180_000)
    review.click()

    marker = page.get_by_text("Same episode", exact=True)
    expect(marker.first).to_be_visible(timeout=30_000)
    card = marker.first.locator("xpath=ancestor::div[contains(@class, 'q-card')][1]")
    box = card.get_by_role("checkbox", name="Include")
    # The cut ran, so the pool shows its picks ticked: tick this one in, then out again.
    if box.get_attribute("aria-checked") != "true":
        box.click()
    expect(box).to_be_checked()
    box.click()
    expect(box).not_to_be_checked()
