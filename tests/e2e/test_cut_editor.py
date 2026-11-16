"""The cut editor keeps an owner's trims: a later end, a trimmed addition, the pool and render (#2953)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from immich_memories.analysis.sources.snapshot import SNAPSHOT_NAME, source_payload
from immich_memories.api.models import Asset
from immich_memories.operations.run_index import record_run_attempt
from immich_memories.operations.storyboard import PLAN_FILE, PROJECTION_FILE
from immich_memories.tracking import RunDatabase
from immich_memories.tracking.models import RunMetadata
from tests.e2e.fake_immich import _asset_payload
from tests.e2e.fake_library import LIBRARY, Picture
from tests.e2e.web_flow import contact_sheet

pytestmark = pytest.mark.e2e

_BY_ID = {picture.asset_id: picture for picture in LIBRARY}
# The cut: a still from home, two from the first day north, the day's clip (1.0-2.5 s of a 5 s
# file) and a still after the 14th, when the clip the owner adds was taken.
_CUT = (
    "home-0702-kit-stuffie",
    "north-0712-0012",
    "north-clip-0712-0",
    "trip-0712-bike-harbour",
    next(
        p.asset_id for p in LIBRARY if p.shipped and not p.is_video and p.taken_at >= "2025-07-16"
    ),
)
_CLIP = "north-clip-0712-0"
_ADDED_CLIP = "north-clip-0714-1"
_ADDED_STILL = "north-0713-0016"
_OTHER_STILL = "north-0713-0017"


def _asset(picture: Picture) -> Asset:
    return Asset.model_validate(_asset_payload(picture))


def _seed(workspace, run_id: str) -> str:
    """A saved cut of five shots whose pool holds a few more pictures, one of them a clip."""
    RunDatabase(workspace.store()).save_run(
        RunMetadata(
            run_id=run_id,
            created_at=datetime.now(UTC),
            status="completed",
            memory_type="monthly_highlights",
        )
    )
    attempt = workspace.cache_dir / "editorial-runs" / run_id / "attempts" / "a1"
    attempt.mkdir(parents=True)
    carriers: list[dict[str, Any]] = []
    for index, asset_id in enumerate(_CUT):
        asset = _asset(_BY_ID[asset_id])
        carriers.append(
            {
                "asset_id": asset_id,
                "taken": asset.local_taken_at.isoformat(),
                "story_episode": "july",
                "kind": "video" if _BY_ID[asset_id].is_video else "photo",
                "seconds": 3.0,
                "why": "July: a day",
                "depicted_moment": f"m{index}",
            }
        )
    plan = {
        "story": {"thesis": "July.", "episodes": [{"episode": "july", "title": "July"}]},
        "carriers": carriers,
    }
    (attempt / PLAN_FILE).write_text(json.dumps(plan))
    (attempt / PROJECTION_FILE).write_text(json.dumps({"intervals": {_CLIP: [1.0, 2.5]}}))
    pool = [*_CUT, _ADDED_CLIP, _ADDED_STILL, _OTHER_STILL]
    (attempt / SNAPSHOT_NAME).write_text(
        json.dumps(source_payload([_asset(_BY_ID[asset_id]) for asset_id in pool]), default=str)
    )
    record_run_attempt(run_id, attempt, attempt / "film.mp4", store=workspace.store())
    return run_id


@pytest.fixture(autouse=True)
def _no_page_errors(page: Page):
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    yield
    assert errors == []


def _inspector(page: Page):
    return page.get_by_role("article", name="Picture review")


def _ready_player(page: Page):
    player = _inspector(page).locator("video")
    page.wait_for_function("video => video.readyState >= 2", arg=player.element_handle())
    return player


def _seek(page: Page, player, seconds: float) -> None:
    """Pause and move the playhead, as dragging the player's bar does."""
    player.evaluate(f"video => {{ video.pause(); video.currentTime = {seconds}; }}")
    page.wait_for_function(
        f"video => !video.seeking && Math.abs(video.currentTime - {seconds}) < 0.05",
        arg=player.element_handle(),
    )


def _tick(page: Page, asset_id: str):
    tile = (
        page.get_by_role("list", name="Pool")
        .get_by_role("listitem")
        .filter(has=page.locator(f"img[src*='{asset_id}']"))
    )
    expect(tile).to_be_visible(timeout=30_000)
    return tile.get_by_role("checkbox", name="In the film")


def _revisions(page: Page, base: str, run: str) -> list[dict[str, Any]]:
    return page.request.get(f"{base}/api/v1/runs/{run}/revisions").json()


@pytest.mark.feature("web.review-and-revise")
def test_a_seek_past_the_end_stays_put_and_end_here_sets_a_later_end(
    page: Page, launch_app_url: str, launch_workspace
) -> None:
    """A seek past the range's end was pulled back to its start: an end could never move later."""
    run = _seed(launch_workspace, "20250731_cut_seek")
    page.goto(f"{launch_app_url}/app/runs/{run}")
    page.get_by_role("radio", name="Videos").click()
    contact_sheet(page).first.click()
    inspector = _inspector(page)
    expect(inspector.get_by_text("1.0–2.5 sec")).to_be_visible()
    player = _ready_player(page)

    _seek(page, player, 4.0)
    page.wait_for_timeout(600)
    assert abs(player.evaluate("video => video.currentTime") - 4.0) < 0.05
    inspector.get_by_role("button", name="End here").click()

    expect(inspector.get_by_text("1.0–4.0 sec")).to_be_visible()
    expect(inspector.get_by_text("3.0 sec on screen")).to_be_visible()
    # Playing through the new end still loops back to the start of the range.
    _seek(page, player, 3.7)
    player.evaluate("video => video.play()")
    page.wait_for_function(
        "video => !video.paused && video.currentTime >= 1.0 && video.currentTime < 2.0",
        arg=player.element_handle(),
        timeout=15_000,
    )


@pytest.mark.feature("web.review-and-revise")
def test_an_added_clip_plays_in_the_cut_in_capture_order_and_its_trim_saves(
    page: Page, launch_app_url: str, launch_workspace
) -> None:
    """An addition was a thumbnail with Take out: no inspector, no range, never trimmable."""
    run = _seed(launch_workspace, "20250731_cut_addition")
    page.goto(f"{launch_app_url}/app/runs/{run}/pool")
    _tick(page, _ADDED_CLIP).check()
    page.get_by_role("button", name="Preview with these choices").click()
    page.wait_for_url(f"**/app/runs/{run}?revision=1", timeout=30_000)

    shots = contact_sheet(page)
    expect(shots).to_have_count(6)
    # Taken on the 14th: after the first day north, before the last still.
    added = shots.nth(4)
    expect(added.get_by_text("Added", exact=True)).to_be_visible()
    expect(added.locator(f"img[src*='{_ADDED_CLIP}']")).to_have_count(1)
    added.click()
    inspector = _inspector(page)
    expect(inspector.get_by_text("You added it from the pool.")).to_be_visible()
    expect(inspector.get_by_role("button", name="Take out")).to_be_visible()
    # It plays as long as the cut's own clip by default, from the start of its file.
    expect(inspector.get_by_text("0.0–1.5 sec")).to_be_visible()

    _seek(page, _ready_player(page), 3.0)
    inspector.get_by_role("button", name="End here").click()
    expect(inspector.get_by_text("0.0–3.0 sec")).to_be_visible()
    page.get_by_role("button", name="Save revision").click()
    expect(page.get_by_role("status")).to_have_text("Saved as revision 2.")

    saved = _revisions(page, launch_app_url, run)[-1]
    assert saved["added"] == [_ADDED_CLIP]
    start, end = saved["segments"][_ADDED_CLIP]
    assert start == 0.0 and abs(end - 3.0) < 0.05


@pytest.mark.feature("web.review-and-revise")
def test_a_trim_and_an_earlier_addition_survive_choosing_more_from_the_pool(
    page: Page, launch_app_url: str, launch_workspace
) -> None:
    """The Pool page posted only its ticks, so a revision saved from it dropped earlier edits."""
    run = _seed(launch_workspace, "20250731_cut_pool")
    page.goto(f"{launch_app_url}/app/runs/{run}")
    page.get_by_role("radio", name="Videos").click()
    contact_sheet(page).first.click()
    inspector = _inspector(page)
    _seek(page, _ready_player(page), 0.5)
    inspector.get_by_role("button", name="Start here").click()
    expect(inspector.get_by_text("0.5–2.5 sec")).to_be_visible()

    # Unsaved, the trim is kept as a revision before the pool opens on it.
    page.get_by_role("link", name="Pool", exact=True).click()
    page.wait_for_url(f"**/app/runs/{run}/pool?revision=1", timeout=30_000)
    _tick(page, _ADDED_STILL).check()
    expect(page.get_by_text("Add: 1 · Take out: 0")).to_be_visible()
    page.get_by_role("button", name="Preview with these choices").click()
    page.wait_for_url(f"**/app/runs/{run}?revision=2", timeout=30_000)

    # Back in the pool from revision 2, its addition is ticked and stays in on the next save.
    page.get_by_role("link", name="Pool", exact=True).click()
    page.wait_for_url(f"**/app/runs/{run}/pool?revision=2", timeout=30_000)
    expect(_tick(page, _ADDED_STILL)).to_be_checked()
    _tick(page, _OTHER_STILL).check()
    page.get_by_role("button", name="Preview with these choices").click()
    page.wait_for_url(f"**/app/runs/{run}?revision=3", timeout=30_000)

    expect(contact_sheet(page).get_by_text("Added", exact=True)).to_have_count(2)
    page.get_by_role("radio", name="Videos").click()
    contact_sheet(page).first.click()
    expect(_inspector(page).get_by_text("0.5–2.5 sec")).to_be_visible()
    latest = _revisions(page, launch_app_url, run)[-1]
    assert sorted(latest["added"]) == sorted([_ADDED_STILL, _OTHER_STILL])
    assert latest["segments"] == {_CLIP: [0.5, 2.5]}


@pytest.mark.feature("web.review-and-revise")
def test_render_saves_unsaved_edits_as_a_revision_before_it_starts(
    page: Page, launch_app_url: str, launch_workspace
) -> None:
    """Render sent only the chosen revision: edits made since the last save were left out."""
    run = _seed(launch_workspace, "20250731_cut_render")
    page.goto(f"{launch_app_url}/app/runs/{run}")
    panel = page.get_by_role("region", name="Render")
    expect(panel.get_by_role("button", name="Render", exact=True)).to_be_visible()

    _inspector(page).get_by_role("button", name="Remove from this cut").click()
    expect(
        panel.get_by_text("Your latest changes are in no revision yet.", exact=False)
    ).to_be_visible()
    expect(panel.get_by_label("What to render")).to_be_disabled()

    asked: list[dict[str, Any]] = []

    def answer(route) -> None:
        # WHY: the render itself is the CLI's; this test checks what the page asks it for.
        asked.append(route.request.post_data_json)
        route.fulfill(status=422, json={"detail": "Stopped by the test."})

    page.route(f"**/api/v1/runs/{run}/renders", answer)
    panel.get_by_role("button", name="Save and render").click()

    expect(panel.get_by_text("Stopped by the test.")).to_be_visible()
    expect(page.get_by_role("status")).to_have_text("Saved as revision 1.")
    assert [request["revision"] for request in asked] == [1]
    assert _revisions(page, launch_app_url, run)[0]["removed"] == [_CUT[0]]
    expect(panel.get_by_role("button", name="Render", exact=True)).to_be_visible()
    expect(panel.get_by_label("What to render")).to_have_value("1")
