"""An owner's edits to a saved cut are kept as numbered revisions beside the run."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from immich_memories.operations.cut_revisions import (
    CutEdits,
    RevisionRefused,
    read_revisions,
    save_revision,
)
from immich_memories.operations.storyboard import PLAN_FILE, PROJECTION_FILE

_PLAN = {
    "story": {"thesis": "June.", "episodes": [{"episode": "june", "title": "June"}]},
    "content_cap_seconds": 12.0,
    "carriers": [
        {
            "asset_id": "garden-1",
            "taken": "2024-06-08T12:00:00",
            "story_episode": "june",
            "kind": "photo",
            "seconds": 3.0,
            "why": "June: lunch",
            "moment_alternatives": ["garden-2", "garden-3"],
        },
        {
            "asset_id": "lake-1",
            "taken": "2024-06-21T18:00:00",
            "story_episode": "june",
            "kind": "video",
            "seconds": 4.0,
            "why": "June: the lake",
        },
    ],
}


@pytest.fixture
def attempt(tmp_path: Path) -> Path:
    (tmp_path / PLAN_FILE).write_text(json.dumps(_PLAN))
    (tmp_path / PROJECTION_FILE).write_text(
        json.dumps({"intervals": {"garden-1": [0.0, 3.0], "lake-1": [10.0, 14.0]}})
    )
    return tmp_path


def test_each_save_is_a_new_numbered_revision_and_the_history_stays(attempt):
    first = save_revision(attempt, CutEdits(removed=("garden-1",)))
    second = save_revision(attempt, CutEdits(segments={"lake-1": (11.0, 13.5)}))

    assert (first.number, second.number) == (1, 2)
    history = read_revisions(attempt)
    assert [revision.number for revision in history] == [1, 2]
    assert history[0].edits.removed == ("garden-1",)
    assert history[1].edits.segments == {"lake-1": (11.0, 13.5)}
    assert history[1].content_seconds == pytest.approx(3.0 + 2.5)


@pytest.mark.parametrize(
    ("edits", "reason"),
    [
        (CutEdits(removed=("never-in-the-cut",)), "not in this cut"),
        (CutEdits(segments={"lake-1": (5.0, 5.0)}), "positive duration"),
        (CutEdits(swaps={"garden-1": "a-stranger"}), "not another picture of that moment"),
        (CutEdits(segments={"lake-1": (0.0, 20.0)}), "12.0 s"),
    ],
)
def test_edits_that_would_not_render_are_refused_with_the_reason(attempt, edits, reason):
    with pytest.raises(RevisionRefused, match=reason):
        save_revision(attempt, edits)

    assert read_revisions(attempt) == []


def test_a_shot_can_be_swapped_for_another_picture_of_its_moment(attempt):
    revision = save_revision(attempt, CutEdits(swaps={"garden-1": "garden-3"}))

    assert read_revisions(attempt)[0].edits.swaps == {"garden-1": "garden-3"}
    assert revision.content_seconds == pytest.approx(7.0)
