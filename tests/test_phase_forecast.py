"""Whole-operation forecasts expose known and unmeasured phases separately."""

from immich_memories.tracking.phase_forecast import PhaseForecast


def test_the_whole_film_includes_music_check_and_delivery_not_just_encoding():
    forecast = PhaseForecast(
        {"prepare": 20.0, "render": 100.0, "music": 30.0, "check": 10.0, "delivery": 5.0},
        target="film",
    )
    forecast.enter("prepare", now=0)
    snapshot = forecast.snapshot(now=5)
    assert snapshot["remaining_seconds"] == 160
    assert snapshot["estimate_basis"] == "previous_run"
    assert snapshot["target"] == "film"
    assert [row["state"] for row in snapshot["phases"]] == ["running", *["pending"] * 4]


def test_a_cold_phase_does_not_hide_the_time_known_for_later_phases():
    forecast = PhaseForecast({"prepare": None, "select": 30.0, "render": 100.0}, target="film")
    forecast.enter("prepare", now=0)
    snapshot = forecast.snapshot(now=5)
    assert snapshot["remaining_seconds"] is None
    assert snapshot["known_remaining_seconds"] == 130
    assert snapshot["unknown_phases"] == ["prepare"]
    assert snapshot["phases"][0]["elapsed_seconds"] == 5


def test_skipped_music_is_visible_and_does_not_consume_a_time_budget():
    forecast = PhaseForecast(
        {"render": 100.0, "music": 30.0, "check": 10.0}, target="film", skipped={"music"}
    )
    forecast.enter("render", now=0)
    forecast.enter("check", now=110)
    snapshot = forecast.snapshot(now=112)
    assert [row["state"] for row in snapshot["phases"]] == ["completed", "skipped", "running"]
    assert snapshot["remaining_seconds"] == 8


def test_overruns_and_additional_preparation_revise_the_forecast():
    forecast = PhaseForecast({"prepare": 10.0, "select": 20.0}, target="cut")
    forecast.enter("prepare", now=0)
    assert forecast.snapshot(now=11)["remaining_seconds"] is None
    forecast.enter("select", now=12)
    forecast.enter("prepare", now=15)
    snapshot = forecast.snapshot(now=16)
    assert snapshot["remaining_seconds"] is None
    assert snapshot["phases"][0]["state"] == "running"
    assert snapshot["phases"][1]["state"] == "pending"
    assert snapshot["revision"] == 1


def test_cut_snapshot_keeps_the_same_phase_forecast_through_disk_and_cli(tmp_path):
    from immich_memories.analysis.editorial_projection import EditorialStageReporter
    from immich_memories.analysis.progress import ProgressTracker
    from immich_memories.operations.cut_progress import StageClock, StageUpdate
    from immich_memories.tracking.span_progress import SpanPlan
    from immich_memories.tracking.timing import Span

    clock = StageClock(
        plan=SpanPlan(
            [
                Span(1, "stage.analysis.previews", None, 0, 20),
                Span(2, "stage.selection.Editing", None, 20, 30),
            ]
        )
    )
    update = clock.measure(StageUpdate("previews", "analysis", 0, 10))
    reloaded = StageUpdate.from_record(update.as_record())
    sent = []
    EditorialStageReporter(ProgressTracker(), sent.append)(reloaded)

    assert update.forecast["target"] == "cut"
    assert update.forecast["remaining_seconds"] == 50
    assert sent[0]["forecast"] == update.forecast
    assert [row["key"] for row in update.forecast["phases"]] == ["analysis", "selection"]


def test_terminal_shows_whole_eta_and_each_phase_beside_the_actual_stage():
    from io import StringIO

    from rich.console import Console

    from immich_memories.cli._live_display import LiveDisplay
    from immich_memories.cli.source_progress import SourceProgressReporter

    stream = StringIO()
    console = Console(file=stream, width=120, color_system=None)
    display = LiveDisplay(console)
    task = display.add_task("Starting")
    forecast = PhaseForecast({"analysis": 20, "selection": 30}, target="cut")
    forecast.enter("analysis", now=0)
    SourceProgressReporter(display, task)(
        {
            "phase_label": "Checking pictures",
            "total_items": 10,
            "current_index": 2,
            "forecast": forecast.snapshot(now=5),
        }
    )
    console.print(display.render())
    output = stream.getvalue()
    assert "About 45s until the cut is ready" in output
    assert "Prepare pictures: running" in output
    assert "Select pictures: pending" in output
    assert "20%" in output


def test_full_generate_keeps_render_phases_in_view_while_selecting(tmp_path):
    from immich_memories.config_loader import Config
    from immich_memories.operations.cut_progress import StageUpdate
    from immich_memories.operations.editorial_attempt import EditorialAttempt
    from immich_memories.tracking.report_context import record_config
    from immich_memories.tracking.timing import collecting

    with collecting():
        record_config(Config(), {"no_render": False, "no_music": True})
        with EditorialAttempt(tmp_path, request={"requested_assets": ["photo"]}) as attempt:
            update = attempt.stage(StageUpdate("Reading pictures", phase="analysis"))
            assert update.forecast["target"] == "film"
            assert [row["key"] for row in update.forecast["phases"]] == [
                "analysis",
                "selection",
                "download",
                "assembly",
                "music",
                "check",
                "upload",
            ]
            assert update.forecast["phases"][4]["state"] == "skipped"


def test_eta_history_uses_a_completed_run_with_the_same_execution_profile():
    from immich_memories.config_loader import Config
    from immich_memories.db import open_store
    from immich_memories.tracking import RunTracker
    from immich_memories.tracking.span_store import SpanStore
    from immich_memories.tracking.timing import Collector, Span

    store = open_store(Config())
    history = SpanStore(store)
    for profile, seconds in [({"tier": "basic"}, 20), ({"tier": "gpu"}, 2)]:
        tracker = RunTracker(store=store, capture_system=False)
        tracker.start_run(source="manual")
        history.save(
            tracker.run_id,
            Collector(spans=[Span(1, "render.assembly", None, 0, seconds)]),
            progress_profile=profile,
        )
        tracker.complete_run()
    reference = history.latest("manual", prefix="render.", profile={"tier": "basic"})
    assert reference.spans[0].duration == 20
    assert history.latest("manual", prefix="render.", profile={"tier": "full"}) is None


def test_a_saved_forecast_expires_during_a_silent_wait_without_new_work():
    from immich_memories.tracking.phase_forecast import forecast_at

    forecast = PhaseForecast({"analysis": 10, "selection": 20}, target="cut")
    forecast.enter("analysis", now=0)
    saved = forecast.snapshot(now=2)
    later = forecast_at(saved, now=saved["observed_at"] + 9)
    assert later["remaining_seconds"] is None
    assert later["known_remaining_seconds"] == 20
    assert later["phases"][0]["elapsed_seconds"] == 11
    assert later["unknown_phases"] == ["analysis"]
    assert saved["remaining_seconds"] == 28  # Read-side projection never rewrites evidence.


def test_first_pass_rate_contributes_to_the_whole_jobs_estimated_work():
    from immich_memories.cli.forecast_display import forecast_lines
    from immich_memories.operations.cut_progress import StageClock, StageUpdate
    from immich_memories.tracking.timing import collecting

    now = [0.0]
    with collecting(now=lambda: now[0]):
        clock = StageClock()
        clock.measure(StageUpdate("previews", "analysis", 0, 1000))
        now[0] = 30
        update = clock.measure(StageUpdate("previews", "analysis", 100, 1000))
        forecast = update.forecast
        assert forecast["remaining_seconds"] is None
        assert forecast["known_remaining_seconds"] == 270
        assert forecast["phases"][0]["known_remaining_seconds"] == 270
        assert "About 5 min of estimated work left" in forecast_lines(forecast)[0]
        assert "unestimated" in forecast_lines(forecast)[0]
        # Another producer cannot inherit the preview pass's measured rate.
        next_pass = clock.measure(StageUpdate("public_heads", "analysis", 0, 1000))
        assert next_pass.forecast["known_remaining_seconds"] == 0


def test_current_rate_replaces_history_for_the_current_pass_only():
    from immich_memories.operations.cut_progress import StageClock, StageUpdate
    from immich_memories.tracking.span_progress import SpanPlan
    from immich_memories.tracking.timing import Span, collecting

    now = [0.0]
    with collecting(now=lambda: now[0]):
        clock = StageClock(
            plan=SpanPlan(
                [
                    Span(1, "stage.analysis.previews", None, 0, 20),
                    Span(2, "stage.analysis.faces", None, 20, 40),
                    Span(3, "stage.selection.Editing", None, 60, 30),
                ]
            )
        )
        clock.measure(StageUpdate("previews", "analysis", 0, 1000))
        now[0] = 30
        update = clock.measure(StageUpdate("previews", "analysis", 100, 1000))
        # 270 seconds of previews at this run's rate, then 40 + 30 from history.
        assert update.forecast["remaining_seconds"] == 340
        assert update.forecast["phases"][0]["remaining_seconds"] == 310
        assert update.forecast["estimate_basis"] == "mixed"


def test_partial_current_rate_ages_without_turning_into_a_completion_promise():
    from immich_memories.tracking.phase_forecast import forecast_at

    forecast = PhaseForecast({"analysis": None, "selection": 20}, target="cut")
    forecast.enter("analysis", now=0)
    forecast.measure_remaining("analysis", 30, now=5, partial=True)
    saved = forecast.snapshot(now=5)
    later = forecast_at(saved, now=saved["observed_at"] + 10)
    assert later["known_remaining_seconds"] == 40
    assert later["remaining_seconds"] is None
    expired = forecast_at(saved, now=saved["observed_at"] + 35)
    assert expired["known_remaining_seconds"] == 20
    assert expired["phases"][0]["remaining_seconds"] is None
    assert saved["known_remaining_seconds"] == 50


def test_quiet_cli_prints_the_first_measured_estimate_without_waiting_a_minute(caplog):
    import logging

    from immich_memories.cli._live_display import QuietDisplay

    forecast = PhaseForecast({"analysis": None, "selection": None}, target="cut")
    forecast.enter("analysis", now=0)
    with caplog.at_level(logging.INFO), QuietDisplay() as display:
        task = display.add_task("Preparing pictures")
        display.update(task, forecast=forecast.snapshot(now=0))
        forecast.measure_remaining("analysis", 270, now=30, partial=True)
        display.update(task, forecast=forecast.snapshot(now=30))
    assert "About 5 min of estimated work left" in caplog.text
