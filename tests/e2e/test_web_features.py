"""Web promises the docs make, driven through the browser on the hermetic launch.

Each test drives the real server and the built client; the store, the output folder and the
fake Immich are the launch workspace's own.
"""

from __future__ import annotations

import io
import json
import re
import shlex
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import Page, expect

from immich_memories.tracking import RunDatabase
from immich_memories.tracking.models import DeliveryStatus, RunMetadata
from tests.e2e.fake_immich import FakeImmichServer
from tests.e2e.fake_library import CARRIERS, MONTH, THESIS, YEAR
from tests.e2e.test_web_client import _seed

pytestmark = pytest.mark.e2e

_DEMO = re.compile(r"\bdemo-mode\b")


@pytest.fixture(autouse=True)
def _no_page_errors(page: Page):
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    yield
    assert errors == []


def _brief_for_the_month(page: Page, launch_app_url: str) -> None:
    page.goto(f"{launch_app_url}/app/create", wait_until="domcontentloaded", timeout=30_000)
    page.get_by_text("Monthly Highlights", exact=True).click()
    page.get_by_label("Year", exact=True).fill(str(YEAR))
    page.get_by_label("Month", exact=True).select_option(str(MONTH))


def _attempts(launch_workspace) -> set[Path]:
    return set(launch_workspace.cache_dir.glob("editorial-runs/*/attempts/*"))


@pytest.mark.feature("web.make-a-film")
def test_a_cut_started_on_memory_survives_its_tab_closing(
    page: Page, launch_app_url: str, launch_workspace
) -> None:
    before = _attempts(launch_workspace)
    _brief_for_the_month(page, launch_app_url)
    page.get_by_role("button", name="Cut", exact=True).click()
    expect(page.get_by_role("region", name="Progress")).to_be_visible(timeout=30_000)
    context = page.context

    page.close()
    again = context.new_page()
    again.goto(f"{launch_app_url}/app/create", wait_until="domcontentloaded", timeout=30_000)

    expect(again.get_by_role("region", name="Progress")).to_be_visible(timeout=30_000)
    again.wait_for_url("**/app/runs/**", timeout=240_000)
    expect(again.get_by_text(THESIS)).to_be_visible(timeout=30_000)
    # The server kept the one cut going: the new tab joined it rather than starting another.
    assert len(_attempts(launch_workspace) - before) == 1


@pytest.mark.feature("web.copy-cli-command")
def test_copy_as_cli_command_copies_the_command_the_server_runs(
    page: Page, launch_app_url: str
) -> None:
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    _brief_for_the_month(page, launch_app_url)
    page.get_by_role("button", name="Cut", exact=True).click()
    panel = page.get_by_role("region", name="Progress")
    expect(panel).to_be_visible(timeout=30_000)
    job = page.request.get(f"{launch_app_url}/api/v1/jobs/active").json()

    panel.get_by_role("button", name="Copy as CLI command").click()
    expect(panel.get_by_role("button", name="Copied")).to_be_visible()
    copied = page.evaluate("navigator.clipboard.readText()")
    panel.get_by_role("button", name="Cancel").click()
    expect(panel.get_by_text("Stopped.")).to_be_visible(timeout=60_000)

    assert copied == job["command"]
    # The same cut as a person types it: every flag the server runs, in its order, minus the
    # server's own file choices (its --config and output paths).
    remaining = iter(job["argv"][1:])
    assert all(word in remaining for word in shlex.split(copied)[1:]), (copied, job["argv"])
    assert copied.startswith(
        f"immich-memories generate --memory-type=monthly_highlights --year={YEAR} --month={MONTH}"
    )


@pytest.mark.feature("web.report-buttons")
@pytest.mark.parametrize("run_id", ["20240701_web_fail", "20240630_web_cut"])
def test_every_run_offers_copy_and_download_report_and_the_download_is_the_bundle(
    page: Page, launch_app_url: str, launch_workspace, tmp_path, run_id: str
) -> None:
    _seed(launch_workspace)
    page.goto(f"{launch_app_url}/app/runs/{run_id}")

    expect(page.get_by_role("button", name="Copy report", exact=True)).to_be_visible()
    with page.expect_download() as event:
        page.get_by_role("link", name="Download report", exact=True).click()
    bundle = tmp_path / event.value.suggested_filename
    event.value.save_as(bundle)

    shown = page.request.get(f"{launch_app_url}/api/v1/runs/{run_id}/report").json()["markdown"]

    with zipfile.ZipFile(io.BytesIO(bundle.read_bytes())) as archive:
        names = set(archive.namelist())
        report = archive.read("report.md").decode()
        facts = json.loads(archive.read("report.json"))
    assert {"report.md", "report.json"} <= names
    # The download is the report Copy report shows (each is built when asked, so live timings
    # differ), with its machine-readable twin beside it.
    assert report.startswith("## Immich Memories run report")
    assert _headings(report) == _headings(shown)
    assert facts


def _headings(markdown: str) -> list[str]:
    return [line for line in markdown.splitlines() if line.startswith("#")]


@pytest.mark.feature("web.find-and-download")
def test_runs_lists_the_newest_run_first(page: Page, launch_app_url: str, launch_workspace) -> None:
    database = RunDatabase(launch_workspace.store())
    # Ahead of every run the session made, so these two lead the list.
    later = datetime.now(UTC) + timedelta(days=1)
    for run_id, created in (
        ("29990101_older", later),
        ("29990102_newer", later + timedelta(hours=1)),
    ):
        database.save_run(
            RunMetadata(run_id=run_id, created_at=created, status="completed", memory_type="trip")
        )
    page.goto(f"{launch_app_url}/app/runs")

    links = page.locator("a[href^='/app/runs/']")
    expect(links.first).to_have_attribute("href", "/app/runs/29990102_newer")
    expect(links.nth(1)).to_have_attribute("href", "/app/runs/29990101_older")


@pytest.mark.feature("web.find-and-download")
def test_a_delivered_film_whose_local_copy_is_gone_downloads_from_immich(
    page: Page,
    launch_app_url: str,
    launch_workspace,
    fake_immich_server: FakeImmichServer,
    tmp_path,
) -> None:
    clip = next(picture for picture in CARRIERS if picture.is_video)
    RunDatabase(launch_workspace.store()).save_run(
        RunMetadata(
            run_id="20261003_delivered_fetch",
            created_at=datetime.now(UTC),
            status="completed",
            output_path=str(launch_workspace.output_dir / "removed-after-delivery.mp4"),
            delivery_status=DeliveryStatus.DELIVERED,
            immich_asset_id=clip.asset_id,
        )
    )
    original = httpx.get(
        f"{fake_immich_server.base_url}/api/assets/{clip.asset_id}/original",
        headers={"x-api-key": fake_immich_server.api_key},
        timeout=30,
    ).content
    page.goto(f"{launch_app_url}/app/runs/20261003_delivered_fetch")

    with page.expect_download() as event:
        page.get_by_role("link", name="Download film", exact=True).click()
    saved = tmp_path / event.value.suggested_filename
    event.value.save_as(saved)

    assert saved.name == "removed-after-delivery.mp4"
    assert saved.read_bytes() == original


@pytest.mark.feature("web.settings")
def test_settings_names_each_source_locks_file_and_environment_values_and_masks_keys(
    page: Page, launch_app_url: str, fake_immich_server: FakeImmichServer
) -> None:
    served = page.request.get(f"{launch_app_url}/api/v1/settings").text()
    page.goto(f"{launch_app_url}/app/settings")
    page.get_by_text("auth", exact=True).click()

    codec = page.get_by_label("output.codec", exact=True)
    auth = page.get_by_label("auth.enabled", exact=True)
    key = page.get_by_label("immich.api_key", exact=True)
    expect(codec).to_be_disabled()
    expect(page.get_by_text("Set in config.yaml as output.codec", exact=True)).to_be_visible()
    expect(auth).to_be_disabled()
    expect(
        page.get_by_text("Set by IMMICH_MEMORIES_AUTH__ENABLED (environment)", exact=True)
    ).to_be_visible()
    expect(page.locator("details[open]").get_by_text("Default", exact=True).first).to_be_visible()
    # The key the server holds never reaches the browser: the field is a blank password box.
    expect(key).to_have_attribute("type", "password")
    expect(key).to_have_value("")
    assert fake_immich_server.api_key not in served
    assert fake_immich_server.api_key not in page.content()


@pytest.mark.feature("web.settings-checks")
def test_settings_runs_the_preflight_checks_when_asked(page: Page, launch_app_url: str) -> None:
    page.goto(f"{launch_app_url}/app/settings")
    checks = page.get_by_role("list", name="Preflight checks")
    expect(page.get_by_role("button", name="Run the preflight checks")).to_be_visible()
    expect(checks).to_have_count(0)

    page.get_by_role("button", name="Run the preflight checks").click()

    immich = checks.get_by_role("listitem").filter(has_text="Immich")
    expect(immich.first).to_be_visible(timeout=60_000)
    expect(immich.first).to_contain_text("Connected")
    expect(page.get_by_role("button", name="Run the checks again")).to_be_visible()
    # The launch config sets nothing old or unknown, so there is nothing to warn about.
    expect(page.get_by_role("alert", name="Config warnings")).to_have_count(0)


@pytest.mark.feature("web.suggestions")
def test_suggestions_come_back_at_once_and_check_eligibility_makes_no_film(
    page: Page, launch_app_url: str, launch_workspace
) -> None:
    page.goto(f"{launch_app_url}/app/suggestions")
    check = page.get_by_role("button", name="Check eligibility").first
    expect(check).to_be_visible(timeout=60_000)
    runs_before = {run.run_id for run in RunDatabase(launch_workspace.store()).list_runs(limit=500)}
    films_before = set(launch_workspace.output_dir.rglob("*.mp4"))

    # Another visit answers with the last discovery, not an empty page that waits for a new one.
    with page.expect_response("**/api/v1/suggestions") as kept:
        page.reload()
    assert kept.value.json()["computed_at"]
    assert kept.value.json()["candidates"]
    expect(check).to_be_visible(timeout=5_000)
    check.click()
    outcome = page.get_by_text(
        re.compile(r"Eligible\. No video was generated\.|^[a-z ]+: .+")
    ).first
    expect(outcome).to_be_visible(timeout=120_000)

    runs_after = {run.run_id for run in RunDatabase(launch_workspace.store()).list_runs(limit=500)}
    assert runs_after == runs_before
    assert set(launch_workspace.output_dir.rglob("*.mp4")) == films_before


@pytest.mark.feature("web.demo-mode")
def test_demo_mode_blurs_the_pictures_the_browser_shows(
    page: Page, launch_app_url: str, launch_workspace
) -> None:
    _seed(launch_workspace)
    page.goto(f"{launch_app_url}/app/runs/20240630_web_cut")
    picture = page.get_by_role("list", name="Cut contact sheet").locator("img").first
    expect(picture).to_be_visible()
    toggle = page.get_by_role("button", name="Demo mode")
    expect(toggle).to_have_attribute("aria-pressed", "false")
    assert "blur" not in picture.evaluate("image => getComputedStyle(image).filter")

    toggle.click()

    expect(page.locator("body")).to_have_class(_DEMO)
    assert "blur" in picture.evaluate("image => getComputedStyle(image).filter")
