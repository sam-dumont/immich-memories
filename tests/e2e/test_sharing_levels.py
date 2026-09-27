"""Who the film is for: the brief's choice, the CLI flag, and what the run records (#1325)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.cli_bootstrap import CLI_BOOTSTRAP
from tests.e2e.conftest import _build_launch_environment
from tests.e2e.web_flow import contact_sheet

pytestmark = pytest.mark.e2e

_ROOT = Path(__file__).resolve().parents[2]


def _attempts(launch_workspace) -> set[Path]:
    return set(launch_workspace.cache_dir.glob("editorial-runs/*/attempts/*"))


def _attempt_after(launch_workspace, before: set[Path]) -> Path:
    """The attempt this cut wrote, not one an earlier cut is still writing into."""
    written = _attempts(launch_workspace) - before
    assert written, "the cut opened no attempt"
    return max(written, key=lambda path: path.stat().st_mtime)


def _request(attempt: Path) -> dict:
    return json.loads((attempt / "status.private.json").read_text())["request"]


def _cli(launch_workspace, *args: str) -> str:
    result = subprocess.run(
        [
            str(_ROOT / ".venv/bin/python"),
            "-c",
            CLI_BOOTSTRAP,
            str(launch_workspace.config_path),
            str(launch_workspace.root / "state"),
            *args,
        ],
        cwd=_ROOT,
        env=_build_launch_environment(launch_workspace.root),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return f"$ immich-memories {' '.join(args)}\n{result.stdout}"


def test_the_brief_asks_who_will_watch_and_the_cut_is_made_for_them(
    page: Page, launch_app_url: str, launch_workspace
) -> None:
    page.goto(f"{launch_app_url}/app/create", wait_until="domcontentloaded", timeout=30_000)
    page.get_by_text("Monthly Highlights", exact=True).click()
    page.get_by_label("Year", exact=True).fill("2024")
    page.get_by_label("Month", exact=True).fill("6")
    page.get_by_text("Length and pictures").click()
    who = page.get_by_label("Who may see it")
    command = page.get_by_label("Command")
    expect(who).to_have_value("")
    expect(command).not_to_contain_text("--sharing")

    who.select_option("family")
    expect(page.get_by_text("Grandparents, siblings, the group chat.", exact=False)).to_be_visible()
    who.select_option("just-us")
    expect(page.get_by_text("The household.", exact=False)).to_be_visible()
    expect(command).to_contain_text("--sharing=just-us")
    before = _attempts(launch_workspace)
    page.get_by_role("button", name="Cut", exact=True).click()
    page.wait_for_url("**/app/runs/**", timeout=240_000)
    expect(contact_sheet(page).first).to_be_visible(timeout=30_000)

    web_attempt = _attempt_after(launch_workspace, before)
    assert _request(web_attempt)["audience"] == "just_us"

    before = _attempts(launch_workspace)
    month = ["--memory-type", "monthly_highlights", "--year", "2024", "--month", "6"]
    quiet = ["--no-render", "--no-music", "--quiet"]
    transcript = [_cli(launch_workspace, "generate", *month, "--sharing", "shareable", *quiet)]
    cli_attempt = _attempt_after(launch_workspace, before)
    assert _request(cli_attempt)["audience"] == "shareable"
    assert "Sharing: shareable" in transcript[0]
    web_story = _cli(launch_workspace, "runs", "story", str(web_attempt))
    cli_story = _cli(launch_workspace, "runs", "story", str(cli_attempt))
    assert "Sharing: just us" in web_story
    assert "Sharing: shareable" in cli_story
    transcript += [web_story, cli_story]
    evidence = _ROOT / "test-results"
    evidence.mkdir(exist_ok=True)
    (evidence / "sharing-cli.txt").write_text(
        "\n".join(transcript).replace(str(launch_workspace.root), "<fixture-workspace>")
    )
