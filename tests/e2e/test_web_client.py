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
from tests.e2e.web_flow import contact_sheet, cut_june, render, the_film

pytestmark = pytest.mark.e2e


def test_client_shows_the_packaged_build_version(page, launch_app_url):
    version = page.request.get(f"{launch_app_url}/health/live").json()["version"]
    page.goto(f"{launch_app_url}/app/settings")
    expect(page.get_by_test_id("build-version")).to_have_text(f"Immich Memories {version}")


def test_report_is_previewed_before_copying(page, launch_app_url, launch_workspace):
    _seed(launch_workspace)
    report = "## Immich Memories run report\n\n<details><summary>Logs</summary>redacted</details>"
    # WHY: this branch lands with #1428's builder; this test owns the browser/clipboard boundary.
    page.route(
        "**/api/v1/runs/20240701_web_fail/report",
        lambda route: route.fulfill(json={"markdown": report}),
    )
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    page.goto(f"{launch_app_url}/app/runs/20240701_web_fail")
    page.get_by_role("button", name="Copy report", exact=True).click()
    expect(page.get_by_label("Report preview")).to_have_text(report)
    page.get_by_role("button", name="Copy report", exact=True).click()
    expect(page.get_by_role("button", name="Copied", exact=True)).to_be_visible()
    assert page.evaluate("navigator.clipboard.readText()") == report


def test_flagged_captions_are_opt_in_and_previewed(page, launch_app_url, launch_workspace):
    _seed(launch_workspace)
    requests = []

    def report_response(route):
        requests.append(route.request.url)
        included = "include_flagged_captions=true" in route.request.url
        route.fulfill(
            json={
                "markdown": "flagged caption" if included else "no captions",
                "has_flagged_photos": True,
            }
        )

    # WHY: exercise explicit caption consent without requiring the separate free-text producer.
    page.route("**/api/v1/runs/20240701_web_fail/report*", report_response)
    page.goto(f"{launch_app_url}/app/runs/20240701_web_fail")
    page.get_by_role("button", name="Copy report", exact=True).click()
    expect(page.get_by_label("Report preview")).to_have_text("no captions")
    page.get_by_label("Include captions of flagged photos").check()
    expect(page.get_by_label("Report preview")).to_have_text("flagged caption")
    assert len(requests) == 2


def test_a_caption_tick_that_cannot_refresh_goes_back_to_the_report_shown(
    page, launch_app_url, launch_workspace
):
    _seed(launch_workspace)

    def report_response(route):
        if "include_flagged_captions=true" in route.request.url:
            route.fulfill(status=500, json={"detail": "boom"})
        else:
            route.fulfill(json={"markdown": "no captions", "has_flagged_photos": True})

    # WHY: a refresh failing is the server's side; this test owns what the page then shows.
    page.route("**/api/v1/runs/20240701_web_fail/report*", report_response)
    page.goto(f"{launch_app_url}/app/runs/20240701_web_fail")
    page.get_by_role("button", name="Copy report", exact=True).click()
    tick = page.get_by_label("Include captions of flagged photos")
    # WHY: the failed refresh may revert the tick before check() verifies its state.
    tick.click()

    expect(page.get_by_text("The report could not be loaded.")).to_be_visible()
    expect(tick).not_to_be_checked()
    expect(page.get_by_label("Report preview")).to_have_text("no captions")


def test_a_first_cut_shows_its_stage_s_share_and_time_left(page, launch_app_url):
    job = {
        "id": "first-cut",
        "kind": "cut",
        "argv": ["immich-memories", "generate"],
        "status": "running",
        "started_at": datetime.now(UTC).timestamp(),
        "command": "immich-memories generate --no-render",
        "progress": {
            "label": "Preparing previews",
            "phase": "analysis",
            "done": 60,
            "total": 120,
            # No finished run measured the whole cut: the server sends the stage's own numbers.
            "fraction": 0.5,
            "remaining_seconds": None,
            "stage_remaining_seconds": 42.0,
            "recent_asset_ids": [],
        },
    }
    event = f"data: {json.dumps(job)}\n\n"
    # WHY: a cold library's first cut takes minutes; this test owns how its progress is drawn.
    page.route("**/api/v1/jobs/active", lambda route: route.fulfill(json=job))
    page.route(
        "**/api/v1/jobs/first-cut/events",
        lambda route: route.fulfill(body=event, content_type="text/event-stream"),
    )
    page.goto(f"{launch_app_url}/app/create")

    panel = page.get_by_role("region", name="Progress")
    expect(panel.get_by_role("progressbar")).to_have_attribute("aria-valuetext", "50%")
    expect(panel.get_by_text("~42s left in this stage")).to_be_visible()


def _seed(workspace) -> None:
    db = RunDatabase(workspace.store())
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
    record_run_attempt("20240630_web_cut", attempt, attempt / "film.mp4", store=workspace.store())


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
    # The workspace is shared by the session, so other tests' runs are here too: find the seeded one.
    cut = page.get_by_role("listitem").filter(has=page.locator("a[href$='/20240630_web_cut']"))
    pictures = cut.locator("img")
    expect(pictures).to_have_count(4)
    for index in range(4):
        expect(pictures.nth(index)).to_have_js_property("complete", True)
        assert pictures.nth(index).evaluate("image => image.naturalWidth") > 0
    failed = page.get_by_role("listitem").filter(has=page.locator("a[href$='/20240701_web_fail']"))
    expect(failed).to_be_visible()
    _shoot(page, "web-runs")

    page.get_by_role("radio", name="Failed").click()
    expect(failed).to_be_visible()
    expect(cut).to_have_count(0)
    expect(page.get_by_role("listitem").filter(has_text="Completed")).to_have_count(0)


def test_a_cancelled_render_points_to_the_run_of_its_saved_cut(
    page: Page, launch_app_url: str, launch_workspace
) -> None:
    RunDatabase(launch_workspace.store()).save_run(
        RunMetadata(
            run_id="20240702_web_cancelled",
            created_at=datetime.now(UTC),
            status="cancelled",
            memory_type="monthly_highlights",
        )
    )
    page.goto(f"{launch_app_url}/app/runs/20240702_web_cancelled")

    expect(page.get_by_text("Stopped before it saved a film.")).to_be_visible()
    expect(page.get_by_text("No saved cut is available for this run.")).to_have_count(0)


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


def test_a_trim_before_the_window_moves_the_start_and_the_time_on_screen(
    page: Page, launch_app_url: str, launch_workspace
) -> None:
    """#2157: a seek before the window snapped back, and the header kept the old time."""
    _seed(launch_workspace)
    page.goto(f"{launch_app_url}/app/runs")
    page.get_by_role("link").filter(has_text="20240630_web_cut").click()
    inspector = page.get_by_role("article", name="Picture review")
    page.get_by_role("radio", name="Videos").click()
    page.get_by_role("list", name="Cut contact sheet").get_by_role("button").first.click()
    expect(inspector.get_by_text("1.5 s on screen")).to_be_visible()
    player = inspector.locator("video")
    page.wait_for_function("video => video.readyState >= 2", arg=player.element_handle())

    player.evaluate("video => { video.pause(); video.currentTime = 0.4; }")
    page.wait_for_function(
        "video => !video.seeking && Math.abs(video.currentTime - 0.4) < 0.05",
        arg=player.element_handle(),
    )
    inspector.get_by_role("button", name="Start here").click()

    expect(inspector.get_by_text("0.4–2.5 s")).to_be_visible()
    expect(inspector.get_by_text("2.1 s on screen")).to_be_visible()


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
    page.get_by_label("Month", exact=True).select_option("6")
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
    render.get_by_label("No music").check()
    render.get_by_role("button", name="Render", exact=True).click()
    film = render.locator("video")
    expect(film).to_be_visible(timeout=600_000)
    page.wait_for_function(
        "video => video.readyState >= 1 && video.duration > 1",
        arg=film.element_handle(),
        timeout=60_000,
    )
    # The film lives on the run Render made, not the cut: the panel offers that run's download (#2220).
    cut_run = page.url.rsplit("/", 1)[-1]
    download = render.get_by_role("link", name="Download film")
    expect(download).to_be_visible()
    href = download.get_attribute("href") or ""
    assert f"/runs/{cut_run}/" not in href
    assert page.request.get(f"{launch_app_url}{href}").ok
    film_run = render.get_by_role("link", name="Open the film run").get_attribute("href") or ""
    assert film_run.rsplit("/", 1)[-1] != cut_run
    _shoot(page, "web-rendered")


def _cut_in_the_browser(page: Page, launch_app_url: str) -> str:
    page.goto(f"{launch_app_url}/app/create")
    page.get_by_text("Monthly Highlights", exact=True).click()
    page.get_by_label("Year", exact=True).fill("2024")
    page.get_by_label("Month", exact=True).select_option("6")
    page.get_by_role("button", name="Cut", exact=True).click()
    page.wait_for_url("**/app/runs/**", timeout=240_000)
    return page.url.rsplit("/", 1)[-1]


def test_the_pool_s_ticks_go_into_the_film_as_a_revision_without_a_recut(
    page: Page, launch_app_url: str
) -> None:
    run = _cut_in_the_browser(page, launch_app_url)
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
    expect(
        tiles.nth(kept_at).get_by_text("Marked Never use. Tick it to include it in this revision.")
    ).to_be_visible()
    expect(boxes[kept_at]).not_to_be_checked()
    # The owner may override a persistent Never use for this saved revision.
    tiles.nth(left_at).get_by_role("button", name="Never use").click()
    expect(
        tiles.nth(left_at).get_by_text("Marked Never use. Tick it to include it in this revision.")
    ).to_be_visible()
    boxes[left_at].check()
    expect(page.get_by_text("Add: 1 · Take out: 1")).to_be_visible()
    _shoot(page, "web-pool")

    page.get_by_role("button", name="Preview with these choices").click()
    # The same run, with the ticks opened as its first revision: nothing was cut again.
    page.wait_for_url(f"**/app/runs/{run}?revision=1", timeout=30_000)
    expect(page.get_by_role("list", name="Added from the pool").get_by_role("img")).to_have_count(1)
    expect(contact_sheet(page).get_by_text("Removed", exact=True)).to_have_count(1)
    panel = page.get_by_role("region", name="Render")
    expect(panel.get_by_label("What to render")).to_have_value("1")

    render(page, resolution="720p")
    expect(the_film(page)).to_be_visible(timeout=900_000)


def test_expired_sign_in_waits_for_manual_retry(page: Page, launch_app_url: str) -> None:
    # WHY: the session API is the boundary; exercise auto-launch without a real IdP.
    page.route(
        "**/api/v1/session",
        lambda route: route.fulfill(
            json={
                "signed_in": False,
                "provider": "oidc",
                "auto_launch": True,
                "button_text": "Sign in with SSO",
                "username": None,
            }
        ),
    )
    page.route("**/auth/authorize", lambda route: route.fulfill(body="Identity provider"))
    page.goto(f"{launch_app_url}/login?error=signin_expired")
    expect(page.get_by_role("alert")).to_have_text("Sign-in expired. Try again.")
    expect(page).to_have_url(f"{launch_app_url}/app/login?error=signin_expired")
    page.get_by_role("link", name="Sign in with SSO").click()
    expect(page).to_have_url(f"{launch_app_url}/auth/authorize")


def test_fade_controls_save_a_default_and_submit_a_film_override(
    page: Page, launch_app_url: str, launch_workspace
) -> None:
    _seed(launch_workspace)
    page.goto(f"{launch_app_url}/app/settings")
    page.get_by_text("title screens", exact=True).click()
    fade = page.get_by_label("title_screens.fade_color", exact=True)
    expect(fade).to_have_value("white")
    fade.select_option("black")
    section = page.locator("details").filter(has=fade)
    section.get_by_role("button", name="Save", exact=True).click()
    expect(section.get_by_role("status")).to_have_text("Saved to the database")
    page.reload()
    page.get_by_text("title screens", exact=True).click()
    expect(fade).to_have_value("black")

    sent = []

    def record_render(route):
        sent.append(route.request.post_data_json)
        # WHY: inspect the browser's request without writing a whole film.
        route.fulfill(status=422, json={"detail": "Test captured the render request"})

    page.route("**/api/v1/runs/*/renders", record_render)
    cut_june(page, launch_app_url)
    panel = page.get_by_role("region", name="Render")
    choice = panel.get_by_label("Opening and closing fade")
    expect(choice).to_have_value("")
    choice.select_option("white")
    panel.get_by_role("button", name="Render", exact=True).click()
    expect(panel.get_by_role("alert")).to_have_text("Test captured the render request")
    assert sent[-1]["fade_color"] == "white"
    choice.select_option("")
    with page.expect_response("**/api/v1/runs/*/renders"):
        panel.get_by_role("button", name="Render", exact=True).click()
    assert sent[-1]["fade_color"] is None


@pytest.mark.parametrize("missing", [[], ["asset.upload"], ["tag.create", "tag.asset"]])
def test_render_upload_option_explains_permissions_without_disabling_render(
    page, launch_app_url, launch_workspace, missing
):
    _seed(launch_workspace)
    reason = "Upload unavailable: the key lacks " + ", ".join(missing) if missing else None
    page.route(
        "**/api/v1/render/capabilities",
        lambda route: route.fulfill(
            json={
                "upload_available": not missing,
                "missing_upload": missing,
                "upload_reason": reason,
            }
        ),
    )
    page.goto(f"{launch_app_url}/app/runs/20240630_web_cut")
    panel = page.get_by_role("region", name="Render")
    option = panel.get_by_label("Upload the film to Immich")
    if missing:
        expect(option).to_be_disabled()
        expect(panel.get_by_text(reason, exact=True)).to_be_visible()
    else:
        expect(option).to_be_enabled()
    expect(panel.get_by_role("button", name="Render", exact=True)).to_be_enabled()


def test_incomplete_upload_highlights_an_actual_local_film_download(
    page, launch_app_url, launch_workspace, tmp_path
):
    import re

    from immich_memories.tracking.models import DeliveryStatus

    film = launch_workspace.output_dir / "retained-permission-film.mp4"
    film.write_bytes(b"synthetic finished film")
    RunDatabase(launch_workspace.store()).save_run(
        RunMetadata(
            run_id="20261002_permission_download",
            created_at=datetime.now(UTC),
            status="completed",
            output_path=str(film),
            delivery_status=DeliveryStatus.ABANDONED,
            delivery_error="not uploaded: the key lacks asset.upload",
        )
    )
    page.goto(f"{launch_app_url}/app/runs/20261002_permission_download")
    download = page.get_by_role("link", name="Download film", exact=True)
    expect(download).to_have_class(re.compile("bg-primary"))
    expect(page.get_by_text("not uploaded: the key lacks asset.upload", exact=True)).to_be_visible()
    with page.expect_download() as event:
        download.click()
    destination = tmp_path / event.value.suggested_filename
    event.value.save_as(destination)
    assert destination.read_bytes() == film.read_bytes()


def test_delivered_film_still_offers_download_after_local_cleanup(
    page, launch_app_url, launch_workspace
):
    from immich_memories.tracking.models import DeliveryStatus

    RunDatabase(launch_workspace.store()).save_run(
        RunMetadata(
            run_id="20261002_delivered_download",
            created_at=datetime.now(UTC),
            status="completed",
            output_path=str(launch_workspace.output_dir / "already-reclaimed.mp4"),
            delivery_status=DeliveryStatus.DELIVERED,
            immich_asset_id="recorded-delivered-film",
        )
    )
    page.goto(f"{launch_app_url}/app/runs/20261002_delivered_download")
    expect(page.get_by_role("link", name="Download film", exact=True)).to_have_attribute(
        "href", "/api/v1/runs/20261002_delivered_download/download"
    )
    expect(
        page.get_by_text("Delivered to Immich. The local file was removed to save disk space.")
    ).to_be_visible()


@pytest.mark.parametrize("route", ["create", "settings"])
def test_model_acquisition_waits_for_a_click_and_keeps_download_errors_visible(
    page, launch_app_url, route
):
    downloads = []
    artifact = {
        "label": "DINOv2 encoder",
        "host": "github.com",
        "size": "88 MB",
        "sha256": "a" * 64,
        "revision": None,
        "ready": False,
    }
    page.route(
        "**/api/v1/models",
        lambda request: request.fulfill(
            json={"plan_id": "displayed-plan", "ready": False, "artifacts": [artifact]}
        ),
    )
    page.route(
        "**/api/v1/jobs/active",
        lambda request: request.fulfill(content_type="application/json", body="null"),
    )
    job = {
        "id": "a" * 32,
        "kind": "models",
        "argv": ["immich-memories", "models", "fetch"],
        "command": "immich-memories models fetch",
        "status": "running",
        "started_at": datetime.now(UTC).timestamp(),
        "progress": {
            "label": "DINOv2 encoder",
            "fraction": 0,
            "done": 0,
            "total": 2,
            "recent_asset_ids": [],
        },
    }

    def download(request):
        assert request.request.post_data_json == {"plan_id": "displayed-plan"}
        downloads.append(request.request.method)
        request.fulfill(status=202, json=job)

    page.route("**/api/v1/models/fetch", download)
    failed = {**job, "status": "failed", "exit_code": 1}
    page.route("**/api/v1/jobs/" + job["id"], lambda request: request.fulfill(json=failed))
    page.route(
        "**/api/v1/jobs/" + job["id"] + "/events",
        lambda request: request.fulfill(
            content_type="text/event-stream", body="data: " + json.dumps(failed) + "\n\n"
        ),
    )
    page.route(
        "**/api/v1/jobs/" + job["id"] + "/output",
        lambda request: request.fulfill(
            json={"output": "encoder: digest does not match; downloaded bytes discarded"}
        ),
    )

    page.goto(f"{launch_app_url}/app/{route}")

    card = page.get_by_role("region", name="Download models", exact=True)
    expect(card.get_by_text("88 MB · github.com")).to_be_visible()
    expect(card.get_by_text("SHA-256: " + "a" * 64)).to_be_visible()
    assert downloads == []
    card.get_by_role("button", name="Download models", exact=True).click()
    expect(
        card.get_by_text("encoder: digest does not match; downloaded bytes discarded")
    ).to_be_visible()
    expect(card.get_by_role("button", name="Download models", exact=True)).to_be_enabled()
    assert downloads == ["POST"]
    page.reload()
    expect(
        card.get_by_text("encoder: digest does not match; downloaded bytes discarded")
    ).to_be_visible()
    assert downloads == ["POST"]


def test_an_immich_outage_is_not_shown_as_an_empty_library(page, launch_app_url):
    # WHY: the fake Immich is shared by the whole session, so the outage is what the page is told.
    page.route(
        "**/health/ready",
        lambda route: route.fulfill(
            status=503,
            json={"status": "degraded", "immich": {"status": "unreachable", "reachable": False}},
        ),
    )
    page.route("**/api/v1/people", lambda route: route.fulfill(json=[]))
    page.goto(f"{launch_app_url}/app/create")
    expect(page.get_by_text("Immich unreachable")).to_be_visible()
    expect(page.get_by_text("No named people in Immich yet.")).to_have_count(0)
