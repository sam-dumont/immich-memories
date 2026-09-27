"""A saved revision renders from the cut's own render inputs, through the owner-edit engine."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from immich_memories.api.models import AssetType
from immich_memories.operations.cut_revisions import CutEdits, CutRevision
from immich_memories.operations.revision_render import RenderUnavailable, project_revision
from immich_memories.operations.storyboard import PLAN_FILE
from immich_memories.processing.editorial_timing import timing_policy_for_params
from immich_memories.processing.render_inputs import write_render_inputs
from tests.conftest import make_clip
from tests.test_editorial_owner_edits import original_params


@pytest.fixture
def cut(tmp_path):
    params = original_params(tmp_path)
    attempt = tmp_path / "attempt"
    attempt.mkdir()
    write_render_inputs(
        attempt,
        params.clips,
        params.editorial_selections,
        params.clip_segments,
        params.editorial_render_timing,
    )
    carriers = [{"asset_id": c.asset.id} for c in params.clips]
    carriers[0]["moment_alternatives"] = ["sibling-0"]
    (attempt / PLAN_FILE).write_text(json.dumps({"carriers": carriers}))
    return params, attempt


def _sibling(asset_id: str):
    # WHY: Immich is the external boundary; the unit tier has no library to fetch from.
    clip = make_clip(asset_id, duration=12, file_created_at=datetime(2020, 1, 2, tzinfo=UTC))
    clip.asset.type = AssetType.IMAGE
    return clip


def test_a_revision_removes_and_swaps_on_the_cut_s_own_inputs(cut):
    params, attempt = cut
    revision = CutRevision(
        number=1,
        created_at="2026-09-27T08:00:00Z",
        edits=CutEdits(removed=("chosen-1",), swaps={"chosen-0": "sibling-0"}),
        content_seconds=12.0,
    )

    result = project_revision(attempt, revision, _sibling, timing_policy_for_params(params))

    assert [clip.asset.id for clip in result.clips] == ["sibling-0", "chosen-2", "chosen-3"]
    assert result.record["removed_asset_ids"] == ["chosen-1"]
    assert result.record["replacements"] == [{"original": "chosen-0", "replacement": "sibling-0"}]


def test_the_cut_itself_renders_unchanged_with_its_own_binding(cut):
    params, attempt = cut

    result = project_revision(attempt, None, _sibling, timing_policy_for_params(params))

    assert result.record is None
    assert result.binding == params.editorial_render_timing


def test_a_cut_without_render_inputs_says_to_cut_again(tmp_path):
    with pytest.raises(RenderUnavailable, match="Cut again"):
        project_revision(tmp_path, None, _sibling, None)


def test_a_saved_revision_renders_through_generate_memory_with_the_run_s_own_request(
    cut, tmp_path, monkeypatch
):
    from datetime import date

    from immich_memories.generate_saved_cut import CutRenderRequest, render_saved_cut
    from immich_memories.tracking.models import RunMetadata

    params, attempt = cut
    rendered = []
    # WHY: generate_memory writes the film (FFmpeg); the unit tier checks what it is asked.
    monkeypatch.setattr(
        "immich_memories.generate_saved_cut.generate_memory",
        lambda request: rendered.append(request) or request.output_path,
    )
    run = RunMetadata(
        run_id="20260927_080000_abcd",
        created_at=datetime(2026, 9, 27, 8, tzinfo=UTC),
        status="completed",
        memory_type=params.memory_type,
        date_range_start=date(2020, 1, 1),
        date_range_end=date(2023, 12, 31),
    )
    params.config.output.directory = str(tmp_path / "films")
    revision = CutRevision(1, "2026-09-27T08:00:00Z", CutEdits(removed=("chosen-1",)), 12.0)

    path = render_saved_cut(
        config=params.config,
        client=None,
        run=run,
        attempt_dir=attempt,
        revision=revision,
        request=CutRenderRequest(no_music=True, llm_title=False),
    )

    (request,) = rendered
    assert [clip.asset.id for clip in request.clips] == ["chosen-0", "chosen-2", "chosen-3"]
    assert request.target_duration_seconds == params.target_duration_seconds
    assert request.editorial_attempt_dir == attempt
    assert request.editorial_owner_edits["removed_asset_ids"] == ["chosen-1"]
    assert path.parent == tmp_path / "films"
    assert (path.parent / request.editorial_owner_edits["artifact_name"]).is_file()
