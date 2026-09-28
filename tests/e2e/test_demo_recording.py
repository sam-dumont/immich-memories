"""Record the Memory page walkthrough as one video, on the hermetic launch.

One .webm under docs-site/static/demo/raw/ (gitignored): the brief, the cut in
progress, the review it produced, a revision, and the render. It shows the flow in motion for a
reviewer; the docs demo itself is the Remotion recreation under
docs-site/remotion, never a screen recording. Part of `make e2e-full`.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from playwright.sync_api import BrowserContext, Page, Playwright, expect

from tests.e2e.fake_library import THESIS
from tests.e2e.redaction import redact_page
from tests.e2e.web_flow import contact_sheet, render, the_film

pytestmark = [pytest.mark.e2e, pytest.mark.slow]

_VIDEO_SIZE = {"width": 1440, "height": 900}
_THESIS = THESIS


def _recording_context(playwright: Playwright, raw_dir: Path) -> BrowserContext:
    browser = playwright.chromium.launch()
    return browser.new_context(
        viewport=_VIDEO_SIZE, record_video_dir=str(raw_dir), record_video_size=_VIDEO_SIZE
    )


def _save_recording(context: BrowserContext, page: Page, raw_dir: Path, name: str) -> None:
    """Close the page to finalize the recording, then give it the segment's name."""
    page.close()
    video_path = page.video.path() if page.video else None
    context.close()
    if video_path and Path(video_path).exists():
        shutil.move(str(video_path), str(raw_dir / f"{name}.webm"))


def test_record_memory_walkthrough(
    playwright: Playwright, launch_app_url: str, demo_raw_dir: Path
) -> None:
    """Brief, Cut, the review, one edit kept as a revision, the render: one take, real pauses."""
    context = _recording_context(playwright, demo_raw_dir)
    page = context.new_page()

    page.goto(f"{launch_app_url}/app/create", wait_until="domcontentloaded", timeout=30_000)
    page.wait_for_timeout(1200)
    page.get_by_text("Monthly Highlights", exact=True).click()
    page.get_by_label("Year", exact=True).fill("2024")
    page.wait_for_timeout(600)
    page.get_by_label("Month", exact=True).select_option("6")
    page.get_by_text("Length and pictures").click()
    page.get_by_label("Length in minutes", exact=False).fill("2")
    page.wait_for_timeout(1500)

    page.get_by_role("button", name="Cut", exact=True).click()
    page.wait_for_url("**/app/runs/**", timeout=240_000)
    expect(page.get_by_text(_THESIS)).to_be_visible()
    page.wait_for_timeout(2000)
    contact_sheet(page).nth(2).click()
    page.wait_for_timeout(2000)
    page.get_by_role("article", name="Picture review").get_by_role(
        "button", name="Remove from this cut"
    ).click()
    page.wait_for_timeout(1200)
    page.get_by_role("button", name="Save revision").click()
    page.wait_for_timeout(1500)

    page.get_by_role("region", name="Render").scroll_into_view_if_needed()
    page.get_by_role("region", name="Render").get_by_label("What to render").select_option(
        label="Revision 1"
    )
    page.wait_for_timeout(1200)
    render(page, resolution="720p")
    expect(the_film(page)).to_be_visible(timeout=600_000)
    # WHY: the output line names a pytest temp root that carries the developer's user name.
    redact_page(page)
    page.wait_for_timeout(2500)

    _save_recording(context, page, demo_raw_dir, "memory-walkthrough")
