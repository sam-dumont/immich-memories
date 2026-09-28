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


def test_the_owners_edits_are_the_film_even_past_the_titles_budget(tmp_path):
    (tmp_path / PLAN_FILE).write_text(json.dumps(_PLAN))
    # The renderer counts recorded intervals (5 s + 8 s), not the storyboard squeezed to fit.
    (tmp_path / PROJECTION_FILE).write_text(
        json.dumps({"intervals": {"garden-1": [0.0, 5.0], "lake-1": [10.0, 18.0]}})
    )

    longer = save_revision(tmp_path, CutEdits(segments={"lake-1": (10.0, 20.0)}))

    assert longer.content_seconds == pytest.approx(15.0)


def _pool(attempt: Path, *assets) -> None:
    from immich_memories.analysis.editorial_source_snapshot import SNAPSHOT_NAME, source_payload

    (attempt / SNAPSHOT_NAME).write_text(json.dumps(source_payload(list(assets))))


def _photo(asset_id: str, taken: str):
    from datetime import datetime

    from immich_memories.api.models import AssetType
    from tests.conftest import make_asset

    photo = make_asset(asset_id, file_created_at=datetime.fromisoformat(taken), duration=None)
    return photo.model_copy(update={"type": AssetType.IMAGE})


def test_the_owner_adds_a_pool_picture_the_editor_left_out_and_the_film_makes_room(attempt):
    from datetime import datetime

    from tests.conftest import make_asset

    _pool(
        attempt,
        _photo("garden-1", "2024-06-08T12:00:00+00:00"),
        _photo("birthday", "2024-06-15T15:00:00+00:00"),
        make_asset("swim", file_created_at=datetime.fromisoformat("2024-06-18T10:00:00+00:00")),
    )

    revision = save_revision(attempt, CutEdits(added=("birthday", "swim")))

    assert read_revisions(attempt)[0].edits.added == ("birthday", "swim")
    # A still holds as long as the cut's stills (3 s); a video plays as long as its videos (4 s).
    # The owner's word is the last pass: the film grows past the 12 s rather than refuse it.
    assert revision.content_seconds == pytest.approx(3.0 + 4.0 + 3.0 + 4.0)


@pytest.mark.parametrize(
    ("added", "reason"),
    [(("a-stranger",), "not in this cut's pool"), (("garden-1",), "already in the cut")],
)
def test_an_added_picture_has_to_come_from_the_pool_and_be_new_to_the_cut(attempt, added, reason):
    _pool(attempt, _photo("garden-1", "2024-06-08T12:00:00+00:00"))

    with pytest.raises(RevisionRefused, match=reason):
        save_revision(attempt, CutEdits(added=added))
