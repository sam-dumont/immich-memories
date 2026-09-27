"""The scheduler's suggestions and run history are usable from the browser."""

import os
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import set_theme

pytestmark = pytest.mark.e2e


def _card(page: Page, text: str):
    return (
        page.get_by_role("listitem")
        .filter(has=page.get_by_role("button", name="Run this suggestion"))
        .filter(has_text=text)
    )


def _evidence(page: Page, name: str) -> None:
    """Light and dark screenshots for the docs, only when DOCS_SCREENSHOTS names a folder."""
    target = os.environ.get("DOCS_SCREENSHOTS")
    if not target:
        return
    Path(target).mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(Path(target) / f"{name}.png"), full_page=True)
    set_theme(page, "dark")
    page.screenshot(path=str(Path(target) / f"dark-{name}.png"), full_page=True)
    set_theme(page, "light")


def test_suggestions_page_offers_the_discovered_candidates(page, launch_app_url):
    page.goto(f"{launch_app_url}/suggestions")
    page.wait_for_url("**/app/suggestions")
    expect(page.get_by_role("heading", name="Suggestions", level=1)).to_be_visible()
    expect(page.get_by_role("button", name="Refresh suggestions")).to_be_visible()
    expect(page.get_by_role("button", name="Check eligibility").first).to_be_visible(timeout=60_000)


def test_runs_page_reads_the_existing_database(page, launch_app_url, launch_workspace):
    from datetime import datetime

    from immich_memories.tracking import RunDatabase
    from immich_memories.tracking.models import RunMetadata

    db = RunDatabase(launch_workspace.database_path)
    db.save_run(
        RunMetadata(
            run_id="fixture-history",
            created_at=datetime.now(),
            status="failed",
            memory_type="monthly_highlights",
            warnings=["Fixture provider stopped answering"],
        )
    )
    page.goto(f"{launch_app_url}/app/runs")
    page.get_by_role("link").filter(has_text="fixture-history").click()
    expect(page.get_by_text("Fixture provider stopped answering", exact=True)).to_be_visible()


def test_a_failed_generation_still_offers_the_run_it_started(
    page, automation_app_url, automation_workspace
):
    """A failure is exactly when the run record and its transcript are worth reaching."""
    from tests.e2e.fake_automation import FAIL_MARKER

    marker = automation_workspace.root / "state" / FAIL_MARKER
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("")
    page.goto(f"{automation_app_url}/app/suggestions")
    card = _card(page, "Monthly Highlights")
    expect(card).to_be_visible(timeout=60_000)
    card.get_by_role("button", name="Run this suggestion").click()
    expect(page.get_by_text("Failed:", exact=False)).to_be_visible(timeout=120_000)
    expect(page.get_by_role("link", name="Open run", exact=True)).to_be_visible()
    expect(page.get_by_text("the fixture provider refused", exact=False).first).to_be_visible()
    page.get_by_role("link", name="Open run", exact=True).click()
    expect(page.get_by_text("The fixture provider refused the render", exact=True)).to_be_visible()
    expect(page.get_by_role("link", name="Download child output")).to_be_visible()


def test_choose_generate_and_read_the_same_automatic_run(
    page, automation_app_url, automation_workspace
):
    from immich_memories.automation.state_store import AutomationStateStore
    from immich_memories.tracking import RunDatabase
    from immich_memories.web.suggestions import SUGGESTION_REASON
    from tests.e2e.fake_library import CARRIERS, THESIS

    page.goto(f"{automation_app_url}/app/suggestions")
    card = _card(page, "Monthly Highlights")
    expect(card).to_be_visible(timeout=60_000)
    card.get_by_text("Candidate key", exact=True).click()
    expect(
        card.get_by_text("monthly_highlights:2024-06-01:2024-06-30:", exact=False)
    ).to_be_visible()
    card.get_by_role("button", name="Check eligibility").click()
    expect(page.get_by_text("Eligible. No video was generated.", exact=True)).to_be_visible(
        timeout=60_000
    )
    _evidence(page, "suggestions")
    card.get_by_role("button", name="Run this suggestion").click()
    expect(page.get_by_text("Running on the server", exact=False)).to_be_visible(timeout=60_000)
    # A run somebody clicked for is not a nightly wake, and only the live attempt
    # carries that: finishing overwrites the reason with the outcome.
    live = AutomationStateStore(automation_workspace.database_path).get_last_attempt()
    assert live.reason == SUGGESTION_REASON
    expect(page.get_by_role("link", name="Open run", exact=True)).to_be_visible(timeout=660_000)
    page.get_by_role("link", name="Open run", exact=True).click()
    # The review page reads the saved plan after navigating; every other wait on
    # this page is 60 s, and the 5 s default lost the race on CI.
    expect(page.get_by_text(THESIS, exact=True)).to_be_visible(timeout=60_000)
    sheet = page.get_by_role("list", name="Cut contact sheet")
    expect(sheet.get_by_role("button")).to_have_count(len(CARRIERS))
    with page.expect_download() as download:
        page.get_by_role("link", name="Download child output").click()
    transcript = Path(download.value.path()).read_text()
    assert f"Selected {len(CARRIERS)} clips" in transcript
    rows = RunDatabase(automation_workspace.database_path).list_runs(
        status="completed", source="auto"
    )
    assert len(rows) == 1 and rows[0].output_path
    assert Path(rows[0].output_path).is_file()
    assert rows[0].run_id in page.url
    _evidence(page, "run-details")
    page.get_by_role("link", name="Back to runs").click()
    expect(page.get_by_role("link").filter(has_text=rows[0].run_id)).to_be_visible()
    _evidence(page, "runs")
    # A successful child's real generate transcript is also the CLI evidence for this flow.
    target = (
        Path(os.environ.get("UX_EVIDENCE_DIR", str(automation_workspace.root)))
        / "automatic-child-cli.txt"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(transcript.replace(str(automation_workspace.root), "<fixture-workspace>"))


def test_variety_rejections_and_all_sidebar_destinations(page, launch_app_url, launch_workspace):
    from datetime import datetime, timedelta

    from immich_memories.tracking import RunDatabase
    from immich_memories.tracking.models import RunMetadata

    db = RunDatabase(launch_workspace.database_path)
    stamp = datetime.now() + timedelta(seconds=1)
    db.save_run(
        RunMetadata(
            run_id="fixture-variety",
            created_at=stamp,
            completed_at=stamp,
            status="completed",
            source="auto",
            memory_category="person_spotlight",
        )
    )
    page.goto(f"{launch_app_url}/app/suggestions")
    page.get_by_role("button", name="Refresh suggestions").click()
    skipped = page.get_by_text("Why other suggestions were skipped", exact=True)
    expect(skipped).to_be_visible(timeout=60_000)
    skipped.click()
    expect(
        page.get_by_text("The previous automatic memory used this category.", exact=False).first
    ).to_be_visible()
    sidebar = page.get_by_role("navigation", name="Main navigation").first
    for label, path in [
        ("Memory", "/app/create"),
        ("Runs", "/app/runs"),
        ("Settings", "/app/settings"),
        ("Suggestions", "/app/suggestions"),
    ]:
        sidebar.get_by_role("link", name=label, exact=True).click()
        page.wait_for_url(launch_app_url + path)
    sidebar.get_by_role("link", name="Settings", exact=True).click()
    page.get_by_role("link", name="People", exact=False).click()
    page.wait_for_url(f"{launch_app_url}/app/settings/people")


def test_run_history_filters_and_loads_every_page(page, launch_app_url, launch_workspace):
    from datetime import datetime, timedelta

    from immich_memories.tracking import RunDatabase
    from immich_memories.tracking.models import RunMetadata

    db = RunDatabase(launch_workspace.database_path)
    for index in range(25):
        db.save_run(
            RunMetadata(
                run_id=f"history-{index:02d}",
                created_at=datetime(2024, 1, 1) + timedelta(minutes=index),
                status="failed",
            )
        )
    page.goto(f"{launch_app_url}/app/runs")
    page.get_by_role("radio", name="Failed").click()
    cards = page.get_by_role("link").filter(has_text="history-")
    expect(cards.first).to_be_visible()
    # The client pages in 24 at a time as the list scrolls; the 25th arrives with the next page.
    cards.last.scroll_into_view_if_needed()
    expect(cards).to_have_count(25)
    page.get_by_role("radio", name="Completed").click()
    expect(cards).to_have_count(0)
