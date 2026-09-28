"""A person spotlight's pool shows the pictures the person's episodes bring, marked.

The fixture library names people only on the first picture of each scene; the other
views of the same scene were taken minutes later and name nobody. A spotlight on one
person must still offer those views in the pool, marked "Same episode", so the owner
can untick them before the render.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def test_a_spotlight_pool_offers_and_marks_the_pictures_of_the_persons_episodes(
    page: Page, launch_app_url: str
) -> None:
    page.goto(f"{launch_app_url}/app/create", wait_until="domcontentloaded", timeout=30_000)
    page.get_by_text("Person Spotlight", exact=True).click()
    page.get_by_label("Year", exact=True).fill("2024")
    page.get_by_role("group", name="People").get_by_text("Kit", exact=True).click()
    page.get_by_role("button", name="Cut", exact=True).click()
    page.wait_for_url("**/app/runs/**", timeout=240_000)

    page.get_by_role("link", name="Pool", exact=True).click()
    marker = page.get_by_text("Same episode", exact=True)
    expect(marker.first).to_be_visible(timeout=30_000)
    tile = page.get_by_role("listitem").filter(has=marker.first)
    box = tile.first.get_by_role("checkbox", name="In the film")
    # The pool shows the cut's picks ticked: tick this one in, then out again.
    if not box.is_checked():
        box.check()
    expect(box).to_be_checked()
    box.uncheck()
    expect(box).not_to_be_checked()
