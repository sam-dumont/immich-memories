"""The Remotion demo shows the recorded month: its cut, its stories and its edit picks."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
RECORDING = REPO / "tests" / "e2e" / "fixtures" / "recordings" / "monthly_highlights"


@pytest.fixture
def exporter(monkeypatch: pytest.MonkeyPatch):
    """scripts/export-demo-fixture.py, loaded by path: its name is not importable."""
    monkeypatch.setenv("IMMICH_E2E_RECORDING", "monthly_highlights")
    spec = importlib.util.spec_from_file_location(
        "export_demo_fixture", REPO / "scripts" / "export-demo-fixture.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # WHY: the script's dataclass resolves its own module by name while it is defined.
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def test_the_demo_cut_is_the_recorded_run(exporter) -> None:
    cut = exporter._the_cut()
    plan = json.loads((RECORDING / "plan.json").read_text())
    projection = json.loads((RECORDING / "render-projection.json").read_text())

    assert cut.thesis == plan["story"]["thesis"]
    assert [p.asset_id for p in cut.pictures] == projection["selected_ids"]
    # Every shot says why it is there, under the story the recorded run put it in.
    assert all(cut.reason_of[p.asset_id] for p in cut.pictures)
    titles = {episode["title"] for episode in plan["story"]["episodes"]}
    assert set(cut.story_of.values()) <= titles
    assert {story["title"] for story in cut.stories} == set(cut.story_of.values())


def test_the_edit_scene_swaps_a_shot_that_has_an_alternative(exporter) -> None:
    from tests.e2e.fake_editorial import active_edit

    cut = exporter._the_cut()
    shots = exporter._shots(cut)
    swapped, removed = active_edit()

    assert not shots[swapped]["motion"]
    assert shots[swapped]["alternatives"]
    assert removed > swapped
    assert not shots[removed]["motion"]
    assert not shots[removed]["alternatives"]


def test_every_alternative_is_in_the_pool_with_what_the_run_did_with_it(exporter) -> None:
    cut = exporter._the_cut()
    shots = exporter._shots(cut)
    timecodes = {shot.asset_id: shot.timecode for shot in cut.board.shots}
    pool = {card["picture"]: card for card in exporter._pool(cut, shots, timecodes)}

    for shot in shots:
        for alternative in shot["alternatives"]:
            assert alternative in pool
            assert pool[alternative]["outcome"].startswith("Left out at ")
    kept = {shot["picture"] for shot in shots}
    for picture, card in pool.items():
        assert card["outcome"].startswith("In the cut at " if picture in kept else "Left out at ")


def test_the_recording_flag_is_not_a_config_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # The screenshots run the app with this flag set; a name inside the config prefix showed
    # up under Settings > Checks as an unknown key, in the published screenshot.
    from immich_memories.config.loader import Config
    from immich_memories.config.unknown import unknown_environment
    from tests.e2e.fake_editorial import RECORDING_ENV

    monkeypatch.setenv(RECORDING_ENV, "monthly_highlights")

    assert RECORDING_ENV not in unknown_environment(Config)


def test_the_brief_lists_the_whole_household() -> None:
    # The demo's brief drew four people chips while the page lists everyone the library names.
    from tests.e2e.fake_library import CAST

    fixture = (REPO / "docs-site" / "remotion" / "src" / "fixture.ts").read_text()

    assert f"export const CAST = {json.dumps(list(CAST))};" in fixture
