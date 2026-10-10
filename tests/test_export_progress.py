"""Export callbacks share one monotonic scale, including extraction and delivery."""

from immich_memories.config_loader import Config
from immich_memories.generate import GenerationParams
from immich_memories.generate_progress import _PipelineProgress


def test_extraction_and_upload_cannot_finish_or_rewind_the_export_bar(tmp_path):
    seen = []
    params = GenerationParams(
        clips=[],
        output_path=tmp_path / "memory.mp4",
        config=Config(),
        upload_enabled=True,
        progress_callback=lambda _phase, pct, _msg: seen.append(pct),
    )
    progress = _PipelineProgress(params, clip_count=10)
    for phase, pct in [
        ("download", 0),
        ("extract", 0.5),
        ("extract", 1),
        ("extract", 0.2),
        ("unknown", 1),
        ("download", 1),
        ("assembly", 0),
        ("assembly", 1),
        ("music", 0),
        ("music", 1),
        ("upload", 0.95),
    ]:
        progress.report(phase, pct, phase)
    assert seen == sorted(seen)
    assert all(value < 1 for value in seen)
    progress.report("done", 1, "Complete")
    assert seen[-1] == 1


def test_first_render_moves_the_bar_without_inventing_an_eta(tmp_path):
    seen = []
    params = GenerationParams(
        clips=[],
        output_path=tmp_path / "memory.mp4",
        config=Config(),
        progress_callback=lambda _phase, pct, _msg: seen.append(pct),
    )
    progress = _PipelineProgress(params, clip_count=10)
    progress.report("download", 0.5, "Downloading")
    progress.report("assembly", 0.5, "Encoding")
    assert 0 < seen[0] < seen[1] < 1
    assert progress.remaining_seconds is None


def test_fixed_music_offsets_never_become_a_measured_eta(tmp_path):
    import json

    from immich_memories.cli.progress_file import progress_writer
    from immich_memories.tracking.timing import collecting

    path = tmp_path / "progress.json"
    params = GenerationParams(
        clips=[],
        output_path=tmp_path / "film.mp4",
        config=Config(),
        progress_callback=progress_writer(path),
    )
    with collecting():
        progress = _PipelineProgress(params, clip_count=2)
        progress.report("music", 0.85, "Starting music")
        saved = json.loads(path.read_text())

    assert saved["fraction_scope"] == "unknown"
    assert saved["stage_fraction"] is None
    assert saved["remaining_seconds"] is None


def test_a_repeated_sidecar_callback_does_not_refresh_completed_work(tmp_path):
    import json

    from immich_memories.cli.progress_file import progress_writer

    path = tmp_path / "progress.json"
    report = progress_writer(path)
    report("assembly", 0.5, "Encoding")
    first = json.loads(path.read_text())
    report("assembly", 0.5, "Encoding")
    assert json.loads(path.read_text()) == first
    report("check", 1.0, "Checking the finished film")
    checking = json.loads(path.read_text())
    assert checking["pass_id"] > first["pass_id"]
    assert checking["last_completed_at"] == first["last_completed_at"]
    assert checking["stage_history"][-1]["label"] == "Encoding"


def test_render_forecast_includes_playback_check_and_survives_the_sidecar(tmp_path):
    import json

    from immich_memories.cli.progress_file import progress_writer
    from immich_memories.tracking.phase_forecast import PhaseForecast
    from immich_memories.tracking.timing import collecting

    path = tmp_path / "progress.json"
    params = GenerationParams(
        clips=[],
        output_path=tmp_path / "film.mp4",
        config=Config(),
        no_music=True,
        progress_callback=progress_writer(path),
    )
    with collecting() as collected:
        collected.forecast = PhaseForecast(
            {
                "analysis": 5,
                "selection": 5,
                "download": 10,
                "assembly": 20,
                "music": None,
                "check": 10,
                "upload": None,
            },
            target="film",
            skipped={"music", "upload"},
        )
        progress = _PipelineProgress(params, clip_count=2)
        progress.report("assembly", 0.5, "Encoding")
        saved = json.loads(path.read_text())
        assert 29 < saved["forecast"]["remaining_seconds"] <= 30
        assert saved["forecast"]["phases"][-2]["key"] == "check"
        assert saved["forecast"]["phases"][-2]["state"] == "pending"
        progress.report("check", 1, "Checking playback")
        checking = json.loads(path.read_text())
        assert checking["forecast"]["remaining_seconds"] > 9
        assert checking["fraction"] < 1
        progress.report("done", 1, "Ready")
        ready = json.loads(path.read_text())
        assert ready["forecast"]["remaining_seconds"] == 0
        assert all(row["state"] in {"completed", "skipped"} for row in ready["forecast"]["phases"])


def test_saved_cut_cli_reports_phases_without_a_progress_file(caplog):
    import logging

    from immich_memories.cli.render_progress import render_progress
    from immich_memories.tracking.phase_forecast import PhaseForecast
    from immich_memories.tracking.timing import collecting

    with caplog.at_level(logging.INFO), collecting() as collected:
        forecast = PhaseForecast({"assembly": 20, "check": 10}, target="film")
        forecast.enter("assembly", now=0)
        collected.diagnostics["progress"] = {"forecast": forecast.snapshot(now=5)}
        with render_progress(None, interactive=False) as report:
            report("assembly", 0.5, "Encoding film")
    assert "Encoding film" in caplog.text
    assert "About 25s until the film is ready" in caplog.text


def test_repeating_a_wait_does_not_turn_forecast_age_into_new_progress(tmp_path):
    import json

    from immich_memories.cli.progress_file import progress_writer
    from immich_memories.tracking.timing import collecting

    path = tmp_path / "progress.json"
    params = GenerationParams(
        clips=[],
        output_path=tmp_path / "film.mp4",
        config=Config(),
        progress_callback=progress_writer(path),
    )
    now = [0.0]
    with collecting(now=lambda: now[0]):
        progress = _PipelineProgress(params, clip_count=2)
        progress.report("worker_queue", 0, "Waiting for the render worker")
        first = json.loads(path.read_text())
        now[0] = 45.0
        progress.report("worker_queue", 0, "Waiting for the render worker")
        waiting = json.loads(path.read_text())
    assert waiting["updated_at"] == first["updated_at"]
    assert waiting["forecast"]["phases"][1]["elapsed_seconds"] == 45


def test_completed_render_timings_supply_the_next_films_whole_eta(tmp_path):
    import json

    from immich_memories.cli.progress_file import progress_writer
    from immich_memories.db import open_store
    from immich_memories.tracking import RunTracker
    from immich_memories.tracking.forecast_reference import execution_profile
    from immich_memories.tracking.span_store import SpanStore
    from immich_memories.tracking.timing import Collector, Span, collecting

    config = Config()
    tracker = RunTracker(store=open_store(config), capture_system=False)
    tracker.start_run(source="manual")
    SpanStore(tracker.db.store).save(
        tracker.run_id,
        Collector(
            spans=[
                Span(1, "render.clip_extraction", None, 0, 10, items=2),
                Span(2, "render.assembly", None, 10, 20, items=2),
                Span(3, "render.playback_check", None, 30, 5),
            ]
        ),
        progress_profile=execution_profile(config),
    )
    tracker.complete_run()
    path = tmp_path / "progress.json"
    with collecting():
        params = GenerationParams(
            clips=[],
            output_path=tmp_path / "film.mp4",
            config=config,
            no_music=True,
            progress_callback=progress_writer(path),
        )
        progress = _PipelineProgress(params, clip_count=4)
        progress.report("download", 0, "Preparing selected clips")
    saved = json.loads(path.read_text())
    assert saved["forecast"]["remaining_seconds"] == 65
    assert [phase["state"] for phase in saved["forecast"]["phases"]] == [
        "running",
        "pending",
        "skipped",
        "pending",
        "skipped",
    ]


def test_worker_transfer_rate_contributes_without_guessing_other_render_work(tmp_path):
    from immich_memories.tracking.phase_forecast import PhaseForecast
    from immich_memories.tracking.timing import collecting

    now = [0.0]
    with collecting(now=lambda: now[0]) as collected:
        collected.forecast = PhaseForecast({"assembly": None, "check": 20}, target="film")
        params = GenerationParams(clips=[], output_path=tmp_path / "film.mp4", config=Config())
        progress = _PipelineProgress(params, clip_count=2)
        progress.report("worker_download", 0, "Downloading the finished film")
        now[0] = 10
        progress.report("worker_download", 0.25, "Downloading the finished film")
        forecast = collected.diagnostics["progress"]["forecast"]
        assert forecast["known_remaining_seconds"] == 50
        assert forecast["remaining_seconds"] is None
        progress.report("worker_check", 0, "Checking the downloaded film")
        assert collected.diagnostics["progress"]["forecast"]["known_remaining_seconds"] == 20


def test_a_counting_down_history_estimate_is_not_new_worker_progress(tmp_path):
    import json

    from immich_memories.cli.progress_file import progress_writer
    from immich_memories.tracking.phase_forecast import PhaseForecast
    from immich_memories.tracking.timing import collecting

    path = tmp_path / "progress.json"
    now = [0.0]
    with collecting(now=lambda: now[0]) as collected:
        collected.forecast = PhaseForecast({"assembly": 120, "check": 20}, target="film")
        params = GenerationParams(
            clips=[],
            output_path=tmp_path / "film.mp4",
            config=Config(),
            progress_callback=progress_writer(path),
        )
        progress = _PipelineProgress(params, clip_count=2)
        progress.report("worker_queue", 0, "Waiting for the render worker")
        first = json.loads(path.read_text())
        now[0] = 45
        progress.report("worker_queue", 0, "Waiting for the render worker")
        waiting = json.loads(path.read_text())
    assert waiting["remaining_seconds"] < first["remaining_seconds"]
    assert waiting["updated_at"] == first["updated_at"]
