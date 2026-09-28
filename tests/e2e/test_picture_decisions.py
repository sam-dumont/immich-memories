"""The owner's word on one picture, from the pool and the terminal (#1324)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from immich_memories.config_loader import Config
from immich_memories.db import Store, upsert
from immich_memories.db.tables import head_facts
from immich_memories.store import owner_decisions
from tests.e2e.cli_bootstrap import CLI_BOOTSTRAP
from tests.e2e.conftest import _build_launch_environment
from tests.e2e.fake_library import CARRIERS, LIBRARY
from tests.e2e.web_flow import cut_june

pytestmark = pytest.mark.e2e

_ROOT = Path(__file__).resolve().parents[2]


def store_of(launch_workspace) -> Store:
    return launch_workspace.store()


def flag_by_the_detector(store: Store, asset_id: str) -> None:
    """Bank a nudity-detector `yes` for one stock picture, as ingest would."""
    version = Config().editorial.head_versions["nsfw_marqo"]
    row = {"asset_id": asset_id, "head": "nsfw_marqo", "version": version, "label": "yes"}
    with store.begin() as connection:
        upsert(connection, head_facts, [row], keys=["asset_id", "head", "version"])


def _frame(locator, name: str) -> None:
    """One element of the walk, when UX_EVIDENCE_DIR is set; the full page loses a dialog."""
    target = os.environ.get("UX_EVIDENCE_DIR")
    if target:
        Path(target).mkdir(parents=True, exist_ok=True)
        locator.screenshot(path=str(Path(target) / f"{name}.png"))


def _cli(launch_workspace, *args: str) -> str:
    result = subprocess.run(
        [
            str(_ROOT / ".venv/bin/python"),
            "-c",
            CLI_BOOTSTRAP,
            str(launch_workspace.config_path),
            str(launch_workspace.root / "state"),
            "pictures",
            *args,
        ],
        cwd=_ROOT,
        env=_build_launch_environment(launch_workspace.root),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return f"$ immich-memories pictures {' '.join(args)}\n{result.stdout}"


def _tile(page: Page, asset_id: str):
    """The pool tile of one picture, loading further pages of the pool until it arrives."""
    pool = page.get_by_role("list", name="Pool")
    expect(pool.get_by_role("listitem").first).to_be_visible(timeout=60_000)
    tile = pool.get_by_role("listitem").filter(has=page.locator(f'img[src*="/{asset_id}/"]'))
    for _ in range(10):
        if tile.count():
            break
        pool.get_by_role("listitem").last.scroll_into_view_if_needed()
        page.wait_for_timeout(500)
    return tile


def test_never_use_and_clear_a_hold_from_the_pool(
    page: Page, launch_app_url: str, launch_workspace
) -> None:
    store = store_of(launch_workspace)
    kept = CARRIERS[1].asset_id
    held = next(picture for picture in LIBRARY if picture not in CARRIERS).asset_id
    flag_by_the_detector(store, held)
    try:
        cut_june(page, launch_app_url)
        page.get_by_role("link", name="Pool", exact=True).click()

        card = _tile(page, held)
        expect(card.get_by_text("Held: a nudity detector flagged it.")).to_be_visible()
        card.get_by_role("button", name="Clear hold").click()
        dialog = page.get_by_role("dialog")
        expect(dialog.get_by_text("Clear this hold?")).to_be_visible()
        _frame(card, "1324-pool-held")
        _frame(dialog, "1324-pool-clear-hold-dialog")

        dialog.get_by_role("button", name="Cancel").click()
        expect(dialog).to_have_count(0)
        assert owner_decisions.decisions(store, [held]) == {}, "cancel writes nothing"

        card.get_by_role("button", name="Clear hold").click()
        # The dialog asks how far it may go, the family by default (#1325).
        films = dialog.get_by_label("Films that may use it")
        expect(films).to_have_value("family")
        films.select_option("just-us")
        dialog.get_by_role("button", name="Clear hold").click()
        expect(card.get_by_text("You cleared its hold for just us", exact=False)).to_be_visible()
        expect(card.get_by_role("button", name="Clear hold")).to_have_count(0)
        assert owner_decisions.decisions(store, [held]) == {held: "cleared_just_us"}
        _frame(card, "1324-pool-cleared")

        # Ruling out a ticked picture unticks it: the pool never says both.
        ticked = _tile(page, kept)
        expect(ticked.get_by_role("checkbox", name="In the film")).to_be_checked()
        ticked.get_by_role("button", name="Never use").click()
        expect(ticked.get_by_text("You'll never use this picture.")).to_be_visible()
        expect(ticked.get_by_role("checkbox", name="In the film")).not_to_be_checked()
        assert owner_decisions.decisions(store, [kept]) == {kept: owner_decisions.NEVER_USE}
        _frame(ticked, "1324-pool-never-use-unticks")
        ticked.get_by_role("button", name="Undo").click()
        expect(ticked.get_by_role("button", name="Never use")).to_be_visible()
        assert owner_decisions.decisions(store, [kept]) == {}

        transcript = [
            _cli(launch_workspace, "list"),
            _cli(launch_workspace, "show", held),
            _cli(launch_workspace, "undo", held),
            _cli(launch_workspace, "show", held),
            _cli(launch_workspace, "clear-hold", held, "--level", "anyone", "--yes"),
            _cli(launch_workspace, "never-use", held),
            _cli(launch_workspace, "show", held),
        ]
        assert "You cleared its hold for just us" in transcript[1]
        assert "Cleared for anyone" in transcript[4]
        assert "Held: a nudity detector flagged it." in transcript[3]
        assert "You'll never use this picture." in transcript[6]
        evidence = _ROOT / "test-results"
        evidence.mkdir(exist_ok=True)
        (evidence / "pictures-cli.txt").write_text(
            "\n".join(transcript).replace(str(launch_workspace.root), "<fixture-workspace>")
        )
    finally:
        for asset_id in (held, kept):
            owner_decisions.forget(store, asset_id)
