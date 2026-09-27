"""The Svelte client reads the same runs, cuts and pictures as the server pages (#1395)."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from immich_memories.operations.run_index import record_run_attempt
from immich_memories.operations.storyboard import PLAN_FILE, PROJECTION_FILE
from immich_memories.tracking import RunDatabase
from immich_memories.tracking.models import RunMetadata
from tests.e2e.fake_library import CARRIERS, LIBRARY

pytestmark = pytest.mark.e2e


def _seed(workspace) -> None:
    db = RunDatabase(workspace.database_path)
    if db.get_run("20240630_web_cut"):
        return  # the launch workspace lives for the whole session
    now = datetime.now(UTC)
    db.save_run(
        RunMetadata(
            run_id="20240630_web_cut",
            created_at=now - timedelta(hours=2),
            status="completed",
            memory_type="monthly_highlights",
        )
    )
    db.save_run(
        RunMetadata(
            run_id="20240701_web_fail",
            created_at=now - timedelta(minutes=5),
            status="failed",
            memory_type="trip",
        )
    )
    attempt = workspace.cache_dir / "editorial-runs" / "web-cut" / "attempts" / "a1"
    attempt.mkdir(parents=True, exist_ok=True)
    stills = [picture for picture in CARRIERS if not picture.is_video][:4]
    shots = [*stills, next(picture for picture in LIBRARY if picture.is_video)]
    spare = [picture for picture in LIBRARY if picture not in CARRIERS and not picture.is_video][:2]
    plan = {
        "story": {"thesis": "June.", "episodes": [{"episode": "june", "title": "June"}]},
        "carriers": [
            {
                "asset_id": shot.asset_id,
                "taken": f"2024-06-{index + 1:02d}T12:00:00",
                "story_episode": "june",
                "kind": "video" if shot.is_video else "photo",
                "seconds": 3.0,
                "why": "June: a day",
                "depicted_moment": f"m{index}",
                "moment_alternatives": [p.asset_id for p in spare] if index == 0 else [],
            }
            for index, shot in enumerate(shots)
        ],
    }
    (attempt / PLAN_FILE).write_text(json.dumps(plan))
    (attempt / PROJECTION_FILE).write_text(
        json.dumps({"intervals": {shots[-1].asset_id: [1.0, 2.5]}})
    )
    record_run_attempt(workspace.cache_dir, "20240630_web_cut", attempt, attempt / "film.mp4")


@pytest.fixture(autouse=True)
def _no_page_errors(page: Page):
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    yield
    assert errors == []


def _shoot(page: Page, name: str) -> None:
    target = os.environ.get("WEB_CLIENT_SCREENSHOTS")
    if target:
        page.screenshot(path=str(Path(target) / f"{name}.png"), full_page=True)


def test_runs_open_as_cards_with_their_cut_and_filter_by_status(
    page: Page, launch_app_url: str, launch_workspace
) -> None:
    _seed(launch_workspace)
    page.goto(f"{launch_app_url}/app/runs")

    expect(page.get_by_role("heading", name="Runs", level=1)).to_be_visible()
    cut = page.get_by_role("listitem").filter(has_text="Monthly Highlights")
    pictures = cut.locator("img")
    expect(pictures).to_have_count(4)
    for index in range(4):
        expect(pictures.nth(index)).to_have_js_property("complete", True)
        assert pictures.nth(index).evaluate("image => image.naturalWidth") > 0
    expect(page.get_by_role("listitem").filter(has_text="Trip")).to_be_visible()
    _shoot(page, "web-runs")

    page.get_by_role("radio", name="Failed").click()
    expect(page.get_by_role("listitem")).to_have_count(1)
    expect(page.get_by_role("listitem").filter(has_text="Trip")).to_be_visible()


def test_the_client_opens_in_the_browser_language(page: Page, launch_app_url: str) -> None:
    page.context.set_extra_http_headers({"Accept-Language": "fr"})
    page.goto(f"{launch_app_url}/app/runs")

    expect(page.get_by_role("heading", name="Exécutions", level=1)).to_be_visible()
    expect(page.locator("html")).to_have_attribute("lang", "fr")


def test_a_saved_dark_theme_is_applied_when_the_page_loads(page: Page, launch_app_url: str) -> None:
    page.goto(f"{launch_app_url}/app/runs")
    page.evaluate("localStorage.setItem('immich-ui-theme', JSON.stringify('dark'))")
    page.reload()

    expect(page.locator("html")).to_have_class("dark")
    background = page.evaluate("getComputedStyle(document.body).backgroundColor")
    assert background != "rgb(255, 255, 255)"


def test_a_cut_opens_as_a_contact_sheet_that_explains_and_plays_each_shot(
    page: Page, launch_app_url: str, launch_workspace
) -> None:
    _seed(launch_workspace)
    page.goto(f"{launch_app_url}/app/runs")
    page.get_by_role("link").filter(has_text="20240630_web_cut").click()

    sheet = page.get_by_role("list", name="Cut contact sheet")
    shots = sheet.get_by_role("button")
    expect(shots).to_have_count(5)
    inspector = page.get_by_role("article", name="Picture review")
    expect(inspector.get_by_text("a day", exact=True)).to_be_visible()
    expect(inspector.get_by_text("No model read this cut", exact=False)).to_be_visible()

    siblings = inspector.get_by_role("list", name="Other pictures of this moment").get_by_role(
        "button"
    )
    expect(siblings).to_have_count(2)
    siblings.first.click()
    expect(inspector.get_by_text("In the cut", exact=True)).to_be_visible()
    # This run kept no selection trace, and the page says so rather than inventing a fate.
    expect(inspector.get_by_text("Outcome not recorded for this cut", exact=False)).to_be_visible()

    shots.first.focus()
    page.keyboard.press("ArrowRight")
    expect(shots.nth(1)).to_have_attribute("aria-pressed", "true")

    page.get_by_role("radio", name="Videos").click()
    expect(shots).to_have_count(1)
    shots.first.click()
    player = inspector.locator("video")
    expect(player).to_be_visible()
    page.wait_for_function(
        "video => video.readyState >= 2 && video.currentTime >= 1.0 && video.currentTime <= 2.6",
        arg=player.element_handle(),
        timeout=30_000,
    )
    _shoot(page, "web-review")


def test_edits_undo_save_as_a_revision_and_reopen_after_a_reload(
    page: Page, launch_app_url: str, launch_workspace
) -> None:
    _seed(launch_workspace)
    page.goto(f"{launch_app_url}/app/runs")
    page.get_by_role("link").filter(has_text="20240630_web_cut").click()
    shots = page.get_by_role("list", name="Cut contact sheet").get_by_role("button")
    inspector = page.get_by_role("article", name="Picture review")
    expect(shots).to_have_count(5)

    inspector.get_by_role("button", name="Remove from this cut").click()
    expect(shots.first.get_by_text("Removed")).to_be_visible()
    page.get_by_role("button", name="Undo").click()
    expect(shots.first.get_by_text("Removed")).to_have_count(0)

    siblings = inspector.get_by_role("list", name="Other pictures of this moment").get_by_role(
        "button"
    )
    siblings.first.click()
    inspector.get_by_role("button", name="Use this picture instead").click()
    expect(shots.first.get_by_text("Swapped")).to_be_visible()
    shots.nth(1).click()
    inspector.get_by_role("button", name="Remove from this cut").click()
    page.get_by_role("button", name="Save revision").click()
    expect(page.get_by_role("status")).to_have_text("Saved as revision 1.")
    expect(page.get_by_role("button", name="Save revision")).to_be_disabled()
    _shoot(page, "web-revision")

    page.reload()
    expect(shots.nth(1).get_by_text("Removed")).to_have_count(0)
    page.get_by_role("button", name="Open", exact=True).click()
    expect(shots.first.get_by_text("Swapped")).to_be_visible()
    expect(shots.nth(1).get_by_text("Removed")).to_be_visible()


def test_a_memory_made_in_the_browser_is_cut_reviewed_revised_rendered_and_played(
    page: Page, launch_app_url: str
) -> None:
    """The whole loop through the real CLI: generate --no-render, a revision, runs render."""
    page.goto(f"{launch_app_url}/app/create")
    page.get_by_text("Monthly Highlights", exact=True).click()
    page.get_by_label("Year", exact=True).fill("2024")
    page.get_by_label("Month", exact=True).fill("6")
    # WHY two minutes: the fixture editor keeps all eighteen carriers (79 s) whatever the
    # length; a real cut fits its budget, so the brief asks for one this cut fits.
    page.get_by_text("Length and pictures").click()
    page.get_by_label("Length in minutes", exact=False).fill("2")
    command = page.get_by_label("Command")
    expect(command).to_have_text(
        "immich-memories generate --memory-type=monthly_highlights --year=2024 --month=6 "
        "--duration=120 --include-photos --include-live-photos --no-render"
    )
    page.get_by_role("button", name="Cut", exact=True).click()

    expect(page.get_by_role("region", name="Progress")).to_be_visible()
    page.wait_for_url("**/app/runs/**", timeout=240_000)
    sheet = page.get_by_role("list", name="Cut contact sheet")
    expect(sheet.get_by_role("button").first).to_be_visible(timeout=30_000)
    shots = sheet.get_by_role("button").count()
    assert shots >= 3

    page.get_by_role("article", name="Picture review").get_by_role(
        "button", name="Remove from this cut"
    ).click()
    page.get_by_role("button", name="Save revision").click()
    expect(page.get_by_role("status")).to_have_text("Saved as revision 1.")

    render = page.get_by_role("region", name="Render")
    render.get_by_label("What to render").select_option(label="Revision 1")
    render.get_by_label("Music").uncheck()
    render.get_by_role("button", name="Render", exact=True).click()
    film = render.locator("video")
    expect(film).to_be_visible(timeout=600_000)
    page.wait_for_function(
        "video => video.readyState >= 1 && video.duration > 1",
        arg=film.element_handle(),
        timeout=60_000,
    )
    _shoot(page, "web-rendered")


def _cut_in_the_browser(page: Page, launch_app_url: str) -> str:
    page.goto(f"{launch_app_url}/app/create")
    page.get_by_text("Monthly Highlights", exact=True).click()
    page.get_by_label("Year", exact=True).fill("2024")
    page.get_by_label("Month", exact=True).fill("6")
    page.get_by_role("button", name="Cut", exact=True).click()
    page.wait_for_url("**/app/runs/**", timeout=240_000)
    return page.url.rsplit("/", 1)[-1]


def test_the_pool_of_a_cut_takes_the_owner_s_word_and_cuts_again(
    page: Page, launch_app_url: str
) -> None:
    first = _cut_in_the_browser(page, launch_app_url)
    page.get_by_role("link", name="Pool", exact=True).click()
    pool = page.get_by_role("list", name="Pool")
    expect(pool.get_by_role("listitem").first).to_be_visible(timeout=30_000)
    # The pool is the whole library window, so more pictures than the cut kept.
    assert pool.get_by_role("listitem").count() > len(CARRIERS)

    tiles = pool.get_by_role("listitem")
    boxes = [tiles.nth(i).get_by_role("checkbox") for i in range(tiles.count())]
    kept_at = next(i for i, box in enumerate(boxes) if box.is_checked())
    left_at = next(i for i, box in enumerate(boxes) if not box.is_checked())
    tiles.nth(kept_at).get_by_role("button", name="Never use").click()
    expect(tiles.nth(kept_at).get_by_text("You'll never use this picture.")).to_be_visible()
    expect(boxes[kept_at]).not_to_be_checked()
    boxes[left_at].check()
    expect(page.get_by_text("Keep: 1 · Leave out: 1")).to_be_visible()
    _shoot(page, "web-pool")

    page.get_by_role("button", name="Cut again with these choices").click()
    page.wait_for_url(lambda url: "/app/runs/" in url and first not in url, timeout=240_000)
