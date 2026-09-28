"""The browser steps every web e2e shares: make a cut, change it in the pool, render it."""

from __future__ import annotations

import os
import signal
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from playwright.sync_api import Page, expect

from immich_memories.tracking.models import RunMetadata
from immich_memories.tracking.run_database import RunDatabase


def contact_sheet(page: Page):
    return page.get_by_role("list", name="Cut contact sheet").get_by_role("button")


def cut_june(page: Page, launch_app_url: str, *, minutes: float | None = 2) -> str:
    """Make the fixture's June monthly cut in the browser; return the run it lands on.

    WHY two minutes by default: the fixture editor keeps all eighteen carriers (79 s) whatever
    the length asked, and a cut over its budget cannot be rendered as cut.
    """
    page.goto(f"{launch_app_url}/app/create", wait_until="domcontentloaded", timeout=30_000)
    page.get_by_text("Monthly Highlights", exact=True).click()
    page.get_by_label("Year", exact=True).fill("2024")
    page.get_by_label("Month", exact=True).fill("6")
    if minutes is not None:
        page.get_by_text("Length and pictures").click()
        page.get_by_label("Length in minutes", exact=False).fill(str(minutes))
    page.get_by_role("button", name="Cut", exact=True).click()
    page.wait_for_url("**/app/runs/**", timeout=240_000)
    expect(contact_sheet(page).first).to_be_visible(timeout=30_000)
    return page.url.rsplit("/", 1)[-1]


def cut_again_without_the_first_kept(page: Page) -> str:
    """From a review page: untick the first kept picture in the pool and cut again."""
    first = page.url.rsplit("/", 1)[-1]
    page.get_by_role("link", name="Pool", exact=True).click()
    tiles = page.get_by_role("list", name="Pool").get_by_role("listitem")
    expect(tiles.first).to_be_visible(timeout=30_000)
    kept = next(
        tiles.nth(i).get_by_role("checkbox")
        for i in range(tiles.count())
        if tiles.nth(i).get_by_role("checkbox").is_checked()
    )
    kept.uncheck()
    expect(kept).not_to_be_checked()
    page.get_by_role("button", name="Cut again with these choices").click()
    page.wait_for_url(
        lambda url: "/app/runs/" in url and "/pool" not in url and first not in url,
        timeout=240_000,
    )
    expect(contact_sheet(page).first).to_be_visible(timeout=30_000)
    return page.url.rsplit("/", 1)[-1]


def render(page: Page, *, resolution: str, fmt: str = "mp4") -> None:
    """Start a render of the cut on this review page, without music (a hermetic run has none)."""
    panel = page.get_by_role("region", name="Render")
    panel.get_by_label("Resolution").select_option(resolution)
    panel.get_by_label("Format").select_option(fmt)
    panel.get_by_label("No music").check()
    panel.get_by_role("button", name="Render", exact=True).click()


def the_film(page: Page):
    return page.get_by_role("region", name="Render").locator("video")


def wait_for_the_film(page: Page, *, timeout: float) -> None:
    """Wait for the rendered film, but stop as soon as the render says it failed, with why."""
    panel = page.get_by_role("region", name="Render")
    failed = panel.get_by_text("It did not finish.")
    expect(the_film(page).or_(failed)).to_be_visible(timeout=timeout)
    assert not failed.is_visible(), panel.inner_text()


def films(database: RunDatabase) -> list[RunMetadata]:
    """Completed runs that left a film, newest first: a cut run keeps the cut, not a file."""
    return [
        run
        for run in database.list_runs(status="completed", order_by_completion=True)
        if run.output_path and Path(run.output_path).suffix in {".mp4", ".mov"}
    ]


def evidence(page: Page, name: str) -> None:
    """A full-page screenshot under UX_EVIDENCE_DIR, when it is set; nothing otherwise."""
    target = os.environ.get("UX_EVIDENCE_DIR")
    if target:
        Path(target).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(target) / f"{name}.png"), full_page=True)


@contextmanager
def served_ui(env: dict[str, str], port: int, log_path: Path) -> Iterator[str]:
    """`immich-memories ui` as a user starts it, on this port, until the block ends."""
    from tests.e2e.conftest import _REPO_ROOT, _wait_for_server

    url = f"http://127.0.0.1:{port}"
    with log_path.open("w") as log:
        proc = subprocess.Popen(
            [
                str(_REPO_ROOT / ".venv" / "bin" / "immich-memories"),
                "ui",
                "--port",
                str(port),
                "--host",
                "127.0.0.1",
            ],
            stdout=log,
            stderr=log,
            cwd=_REPO_ROOT,
            env=env,
        )
        try:
            _wait_for_server(proc, base_url=url, log_path=log_path)
            yield url
        finally:
            proc.send_signal(signal.SIGINT)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
