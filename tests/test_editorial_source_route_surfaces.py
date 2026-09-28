"""Exercise the opted-in product surfaces without legacy analysis or network work."""

from __future__ import annotations

import socket
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from immich_memories.analysis.editorial_planner import EditorialSelection
from immich_memories.analysis.smart_pipeline import PipelineResult
from immich_memories.api.models import Asset, AssetType, VideoClipInfo
from immich_memories.config_loader import Config
from immich_memories.timeperiod import DateRange
from tests.conftest import make_asset, make_clip

_WHEN = datetime(2026, 7, 10, tzinfo=UTC)
_WINDOW = DateRange(datetime(2026, 7, 1, tzinfo=UTC), datetime(2026, 7, 31, 23, 59, 59, tzinfo=UTC))


def _forbidden(*_args, **_kwargs):
    raise AssertionError("Source-first surface entered a legacy or network boundary")


@pytest.fixture(autouse=True)
def _offline_source_route(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    monkeypatch.setattr(socket, "create_connection", _forbidden)


def _config(tmp_path) -> Config:
    return Config(
        editorial={
            "enabled": True,
            "annotation_database": str(tmp_path / "annotations.db"),
            "description_model": "fake-source-v1",
        },
        cache={"database": str(tmp_path / "analysis.db"), "directory": str(tmp_path / "cache")},
    )


def _photo(asset_id: str) -> Asset:
    return Asset(
        id=asset_id,
        type=AssetType.IMAGE,
        fileCreatedAt=_WHEN,
        fileModifiedAt=_WHEN,
        updatedAt=_WHEN,
    )


def _finished_selection() -> PipelineResult:
    motion = make_clip("selected-motion", duration=7.5, file_created_at=_WHEN)
    still = make_clip("selected-still-frame", duration=8.0, file_created_at=_WHEN)
    photo = VideoClipInfo(asset=_photo("selected-photo"), duration_seconds=3.25)
    # Deliberately nonchronological: the surface must preserve the editor's order,
    # fractional source intervals, and still extraction instruction without replanning.
    selected = [still, photo, motion]
    segments = {
        still.asset.id: (0.0, 4.25),
        photo.asset.id: (0.0, 3.25),
        motion.asset.id: (1.125, 5.375),
    }
    decisions = (
        EditorialSelection(
            asset_id=still.asset.id,
            start_time=0.0,
            end_time=4.25,
            render_mode="still",
            render_frame_seconds=2.375,
        ),
        EditorialSelection(
            asset_id=photo.asset.id, start_time=0.0, end_time=3.25, render_mode="still"
        ),
        EditorialSelection(
            asset_id=motion.asset.id, start_time=1.125, end_time=5.375, render_mode="motion"
        ),
    )
    return PipelineResult(
        selected_clips=selected,
        clip_segments=segments,
        editorial_selections=decisions,
        errors=[],
        stats={"selection_route": "editorial-source"},
    )


def _source_pipeline(result: PipelineResult) -> MagicMock:
    pipeline = MagicMock()
    pipeline.has_editorial_source_route = True
    pipeline.run_editorial_source.return_value = (result.selected_clips, result)
    return pipeline


@pytest.mark.parametrize("no_render", [False, True])
def test_cli_source_route_uses_timed_clips_and_preserves_exact_render_handoff(tmp_path, no_render):
    from immich_memories.cli._pipeline_runner import run_pipeline_and_generate

    result = _finished_selection()
    short = make_asset("short-raw", duration=0.25, file_created_at=_WHEN)
    unknown = make_asset("unknown-raw", duration=None, file_created_at=_WHEN)
    videos = [result.selected_clips[2].asset, short, unknown, result.selected_clips[0].asset]
    photos = [result.selected_clips[1].asset, _photo("unselected-photo")]
    pipeline = _source_pipeline(result)
    output = tmp_path / "album.mp4"
    # WHY: stubs the pipeline builder, the renderer, and the no-render finish path together.
    with (
        # WHY: the collaborator under inspection; its context/dry_run kwargs are asserted.
        patch(
            "immich_memories.analysis.editorial_runtime.build_smart_pipeline", return_value=pipeline
        ) as build,
        patch("immich_memories.generate.generate_memory", return_value=output) as generate,
        patch(
            "immich_memories.cli._pipeline_runner._finish_without_rendering",
            return_value=(output, False, None),
        ) as finish,
    ):
        actual, _, _ = run_pipeline_and_generate(
            assets=videos,
            photo_assets=photos,
            include_photos=True,
            use_live_photos=False,
            client=MagicMock(),
            config=_config(tmp_path),
            progress=MagicMock(),
            duration=60.0,
            transition="cut",
            music=None,
            no_music=True,
            output_path=output,
            memory_type="album",
            person_names=[],
            date_range=_WINDOW,
            date_ranges=(),
            memory_preset_params={"album_name": "Source album", "album_id": "album-source"},
            upload_to_immich=False,
            album=None,
            no_render=no_render,
        )

    assert actual == output
    sources = pipeline.run_editorial_source.call_args.args[0]
    assert [clip.asset for clip in sources[:4]] == videos
    assert [clip.duration_seconds for clip in sources[:4]] == [7.5, 0.25, 0.0, 8.0]
    assert sources[4:] == photos
    assert pipeline.run_editorial_source.call_args.kwargs["include_live_photos"] is False
    context = build.call_args.kwargs["editorial_context"]
    assert context.album_sources == (*videos, *photos)
    assert context.album_ref == "album-source"
    assert context.date_ranges == ()
    assert build.call_args.kwargs["dry_run"] is False
    if no_render:
        generate.assert_not_called()
        assert finish.call_args.kwargs["pipeline_result"] is result
        assert (
            finish.call_args.kwargs["pipeline_result"].stats["selection_route"]
            == "editorial-source"
        )
    else:
        finish.assert_not_called()
        params = generate.call_args.args[0]
        assert params.clips is result.selected_clips
        assert params.clip_segments is result.clip_segments
        assert params.editorial_selections is result.editorial_selections
        assert params.include_photos is False
        assert params.photo_assets is None


@pytest.mark.parametrize("duration", [0.25, None])
def test_cli_short_and_unknown_videos_reach_editor_as_timed_clips(tmp_path, duration):
    from immich_memories.cli._pipeline_runner import run_pipeline_and_generate
    from immich_memories.generate_clips import assets_to_clips

    asset = make_asset("raw-only", duration=duration, file_created_at=_WHEN)
    assert assets_to_clips([asset]) == []
    pipeline = _source_pipeline(_finished_selection())
    pipeline.run_editorial_source.side_effect = RuntimeError("source route reached")
    # WHY: stop at the model boundary; unknown timing belongs to the editor.
    with (
        # WHY: the collaborator under inspection; its call args are asserted after the raise.
        patch(
            "immich_memories.analysis.editorial_runtime.build_smart_pipeline", return_value=pipeline
        ),
        pytest.raises(RuntimeError, match="source route reached"),
    ):
        run_pipeline_and_generate(
            assets=[asset],
            client=MagicMock(),
            config=_config(tmp_path),
            progress=MagicMock(),
            duration=60.0,
            transition="cut",
            music=None,
            no_music=True,
            output_path=tmp_path / "raw.mp4",
            memory_type="monthly_highlights",
            person_names=[],
            date_range=_WINDOW,
            upload_to_immich=False,
            album=None,
            no_render=True,
        )
    sources = pipeline.run_editorial_source.call_args.args[0]
    assert len(sources) == 1 and sources[0].asset == asset
    assert sources[0].duration_seconds == (duration or 0.0)
