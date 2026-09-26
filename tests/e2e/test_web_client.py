"""The Svelte client reads the same runs, cuts and pictures as the server pages (#1395)."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from immich_memories.operations.run_index import record_run_attempt
from immich_memories.operations.storyboard import PLAN_FILE
from immich_memories.tracking import RunDatabase
from immich_memories.tracking.models import RunMetadata
from tests.e2e.fake_library import CARRIERS

pytestmark = pytest.mark.e2e


def _seed(workspace) -> None:
    db = RunDatabase(workspace.database_path)
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
    shots = CARRIERS[:4]
    plan = {
        "story": {"thesis": "June.", "episodes": [{"episode": "june", "title": "June"}]},
        "carriers": [
            {
                "asset_id": shot.asset_id,
                "taken": f"2024-06-{index + 1:02d}T12:00:00",
                "story_episode": "june",
                "kind": "photo",
                "seconds": 3.0,
                "why": "June: a day",
                "depicted_moment": f"m{index}",
            }
            for index, shot in enumerate(shots)
        ],
    }
    (attempt / PLAN_FILE).write_text(json.dumps(plan))
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
