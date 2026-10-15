"""A film's storyboard is the cut it played: the revision's removals, swaps, trims and additions."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from immich_memories.analysis.sources.snapshot import SNAPSHOT_NAME, source_payload
from immich_memories.api.models import AssetType
from immich_memories.operations.film_storyboard import ADDED_REASON, film_storyboard
from immich_memories.operations.storyboard import PLAN_FILE, PROJECTION_FILE
from tests.conftest import make_asset

_PLAN = {
    "story": {"thesis": "June.", "episodes": [{"episode": "june", "title": "June"}]},
    "content_cap_seconds": 10.0,
    "carriers": [
        {
            "asset_id": "garden-1",
            "taken": "2024-06-08T12:00:00",
            "story_episode": "june",
            "kind": "photo",
            "seconds": 3.0,
            "why": "June: lunch",
            "moment_alternatives": ["garden-2"],
        },
        {
            "asset_id": "lake-1",
            "taken": "2024-06-21T18:00:00",
            "story_episode": "june",
            "kind": "video",
            "seconds": 4.0,
            "why": "June: the lake",
        },
        {
            "asset_id": "tent-1",
            "taken": "2024-06-22T08:00:00",
            "story_episode": "june",
            "kind": "photo",
            "seconds": 3.0,
            "why": "June: the tent",
        },
    ],
}


def _photo(asset_id: str, taken: str):
    photo = make_asset(asset_id, file_created_at=datetime.fromisoformat(taken), duration=None)
    return photo.model_copy(update={"type": AssetType.IMAGE})


@pytest.fixture
def attempt(tmp_path: Path) -> Path:
    (tmp_path / PLAN_FILE).write_text(json.dumps(_PLAN))
    intervals = {"garden-1": [0.0, 3.0], "lake-1": [10.0, 14.0], "tent-1": [0.0, 3.0]}
    (tmp_path / PROJECTION_FILE).write_text(json.dumps({"intervals": intervals}))
    pool = [
        _photo("garden-2", "2024-06-08T12:01:00"),
        _photo("birthday", "2024-06-15T15:00:00"),
    ]
    (tmp_path / SNAPSHOT_NAME).write_text(json.dumps(source_payload(pool)))
    return tmp_path


def test_a_film_of_the_cut_as_chosen_reads_the_cut(attempt):
    board = film_storyboard(attempt, None)

    assert board is not None
    assert [shot.asset_id for shot in board.shots] == ["garden-1", "lake-1", "tent-1"]


def test_a_film_from_a_revision_plays_what_the_owner_kept_unsqueezed(attempt):
    edits = {
        "removed_asset_ids": ["tent-1"],
        "replacements": [{"original": "garden-1", "replacement": "garden-2"}],
        "interval_edits": [{"asset_id": "lake-1", "selected_interval": [10.0, 12.0]}],
        "added_asset_ids": ["birthday"],
    }

    board = film_storyboard(attempt, edits)

    assert board is not None
    assert [shot.asset_id for shot in board.shots] == ["garden-2", "birthday", "lake-1"]
    shots = {shot.asset_id: shot for shot in board.shots}
    assert shots["lake-1"].seconds == 2.0
    assert shots["birthday"].reason == ADDED_REASON
    assert shots["birthday"].seconds == 3.0
    # The owner's edits are the last pass: nothing they kept is squeezed into the old budget.
    assert board.total_seconds == 8.0


def test_an_attempt_without_a_plan_has_no_storyboard(tmp_path):
    assert film_storyboard(tmp_path, {"removed_asset_ids": ["x"]}) is None


def test_runs_story_of_a_film_prints_the_revision_it_was_rendered_from(tmp_path):
    from unittest.mock import patch

    from click.testing import CliRunner

    from immich_memories.cli import main
    from immich_memories.db import open_store
    from immich_memories.store.owner_edits import keep_owner_edits
    from tests.web_api_fixtures import config_in, save_run

    config = config_in(tmp_path)
    film = tmp_path / "videos" / "june-film.mp4"
    attempt = save_run(config, "20260913_080000_film", output_path=str(film))
    save_run(config, "20260913_070000_kept", output_path=str(tmp_path / "videos" / "as-cut.mp4"))
    keep_owner_edits(
        open_store(config),
        {"edit_id": "e1", "removed_asset_ids": ["garden-1"]},
        film=film,
        attempt=attempt,
    )

    def story(run_id: str) -> str:
        # WHY: the CLI group loads the user's real config directory on startup.
        with (
            patch("immich_memories.cli.init_config_dir"),
            patch("immich_memories.cli.get_config", return_value=config),
            patch("immich_memories.config.get_config", return_value=config),
        ):
            result = CliRunner().invoke(main, ["runs", "story", run_id], catch_exceptions=False)
        return result.output

    assert "1 picture," in story("20260913_080000_film")
    assert "2 pictures" in story("20260913_070000_kept")
