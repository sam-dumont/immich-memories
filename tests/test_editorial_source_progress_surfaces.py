"""Observed CLI/UI editorial progress without invented completion counts or ETA."""

from io import StringIO
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console

from tests.test_editorial_source_route_surfaces import (
    _WINDOW,
    _config,
    _finished_selection,
    _source_pipeline,
)


def _status(label="Editing the memory", status="running"):
    return {
        "indeterminate": True,
        "status": status,
        "phase_label": label,
        "current_phase": label,
        "started_at": 100.0,
        "elapsed_seconds": 8.25,
        "elapsed": "8s",
    }


@pytest.mark.parametrize("failed", [False, True])
def test_cli_real_display_enters_indeterminate_then_reports_actual_terminal_stage(tmp_path, failed):
    from immich_memories.cli._live_display import LiveDisplay
    from immich_memories.cli._pipeline_runner import run_pipeline_and_generate

    display = LiveDisplay(Console(file=StringIO(), force_terminal=False))
    result = _finished_selection()
    pipeline = _source_pipeline(result)
    observed = []

    def source(_sources, *, progress_callback, **_kwargs):
        for payload in [
            _status("Reading dates, places and people"),
            _status(),
            _status(
                "Editorial selection failed" if failed else "Editorial selection complete",
                "failed" if failed else "complete",
            ),
        ]:
            progress_callback(payload)
            task_id = display._active_task_id
            task = display._progress.tasks[task_id]
            observed.append(
                (payload["status"], display._tasks[task_id].total, task.total, task.description)
            )
        if failed:
            raise RuntimeError("editorial evidence unavailable")
        return result.selected_clips, result

    pipeline.run_editorial_source.side_effect = source
    # WHY: stubs the pipeline builder and renderer so this no-render run never reaches FFmpeg.
    with (
        # WHY: the collaborator under inspection; run_editorial_source calls are asserted below.
        patch(
            "immich_memories.analysis.editorial_runtime.build_smart_pipeline", return_value=pipeline
        ),
        patch(
            "immich_memories.generate.generate_memory",
            side_effect=AssertionError("no render requested"),
        ),
    ):

        def run():
            return run_pipeline_and_generate(
                assets=[result.selected_clips[0].asset, result.selected_clips[2].asset],
                client=MagicMock(),
                config=_config(tmp_path),
                progress=display,
                duration=60.0,
                transition="cut",
                music=None,
                no_music=True,
                output_path=tmp_path / "memory.mp4",
                memory_type="monthly_highlights",
                person_names=[],
                date_range=_WINDOW,
                upload_to_immich=False,
                album=None,
                no_render=True,
            )

        if failed:
            with pytest.raises(RuntimeError, match="editorial evidence unavailable"):
                run()
        else:
            run()
    # The route is proven by what the runner consumed: the editorial source ran
    # once over the admitted clips, and the result it carried says so. The mock
    # pipeline raises on run_analysis/run_planning_analysis/run_selection.
    assert pipeline.run_editorial_source.call_count == 1
    sources = pipeline.run_editorial_source.call_args.args[0]
    assert [clip.asset for clip in sources] == [
        result.selected_clips[0].asset,
        result.selected_clips[2].asset,
    ]
    assert result.stats["selection_route"] == "editorial-source"
    assert observed[:2] == [
        ("running", None, None, "Reading dates, places and people"),
        ("running", None, None, "Editing the memory"),
    ]
    expected = (
        ("failed", None, None, "Editorial selection failed")
        if failed
        else ("complete", 100, 100, "Editorial selection complete")
    )
    assert observed[2] == expected


def test_cached_asset_checks_log_each_stage_once(caplog):
    import logging

    from immich_memories.cli._live_display import QuietDisplay

    display = QuietDisplay()
    with caplog.at_level(logging.INFO, logger="immich_memories.progress"):
        task = display.add_task("Preparing cached previews", total=None)
        for _ in range(1500):
            display.update(task, description="Preparing cached previews")
        assert caplog.messages.count("Preparing cached previews") == 1
        display.update(task, description="Reading the period")
        assert caplog.messages.count("Reading the period") == 1


def test_identical_interactive_description_does_not_refresh_display():
    from immich_memories.cli._live_display import LiveDisplay

    display = LiveDisplay(Console(file=StringIO(), force_terminal=False))
    task = display.add_task("Reading the period", total=None)
    with patch.object(display, "_refresh") as refresh:
        for _ in range(1500):
            display.update(task, description="Reading the period")
        refresh.assert_not_called()
        display.update(task, description="Editorial selection complete")
        refresh.assert_called_once()
