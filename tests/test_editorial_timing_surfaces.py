"""The real CLI parameter builder conserves the frozen editorial title policy."""

from unittest.mock import MagicMock, patch

import pytest

from immich_memories.processing.editorial_timing import (
    bind_editorial_timeline,
    prepare_certified_timeline,
    timing_policy_for_params,
)
from tests.test_editorial_source_route_surfaces import (
    _WINDOW,
    _config,
    _finished_selection,
    _source_pipeline,
)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr("socket.socket.connect", lambda *_a, **_k: pytest.fail("network work"))


def _binding(policy, result):
    assets = {clip.asset.id: clip.asset for clip in result.selected_clips}
    carriers = [{"asset_id": key, "seconds": 4.0} for key in assets]
    return bind_editorial_timeline(policy, policy.resolve(carriers, assets), list(assets))


def test_cli_actual_context_and_generation_reuse_exact_timing(tmp_path):
    from immich_memories.cli._pipeline_runner import run_pipeline_and_generate

    result = _finished_selection()
    pipeline = _source_pipeline(result)
    captured = {}

    def build(**kwargs):
        captured["context"] = kwargs["editorial_context"]
        return pipeline

    def plan(*_args, **_kwargs):
        result.stats["editorial_render_timing"] = _binding(
            captured["context"].render_timing, result
        )
        return result.selected_clips, result

    pipeline.run_editorial_source.side_effect = plan
    output = tmp_path / "memory.mp4"

    def render(params):
        assert params.target_duration_seconds == 60
        assert timing_policy_for_params(params) == captured["context"].render_timing
        prepare_certified_timeline(params)
        assert params.timeline_plan.transition_budget == 0
        assert params.editorial_render_timing is result.stats["editorial_render_timing"]
        return output

    # WHY: replaces the selection pipeline and render step so timing context can be checked.
    with (
        # WHY: the pipeline is a stand-in; its side effect captures the editorial context passed.
        patch("immich_memories.analysis.editorial_runtime.build_smart_pipeline", side_effect=build),
        # WHY: replaces the FFmpeg render; the side effect asserts on the params it receives.
        patch("immich_memories.generate.generate_memory", side_effect=render) as generated,
    ):
        run_pipeline_and_generate(
            assets=[result.selected_clips[0].asset, result.selected_clips[2].asset],
            photo_assets=[result.selected_clips[1].asset],
            include_photos=True,
            client=MagicMock(),
            config=_config(tmp_path),
            progress=MagicMock(),
            duration=60,
            transition="cut",
            music=None,
            no_music=True,
            output_path=output,
            memory_type="monthly_highlights",
            person_names=[],
            date_range=_WINDOW,
            upload_to_immich=False,
            album=None,
        )
    generated.assert_called_once()
