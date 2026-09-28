"""Contracts for the shared, durable outer pipeline lifecycle."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy.exc import OperationalError

from immich_memories.analysis.smart_pipeline import ClipWithSegment, PipelineResult
from immich_memories.automation.state_store import AutomationStateStore
from immich_memories.config_loader import Config
from immich_memories.operations.phases import OperationalPhase, PhaseEvent
from immich_memories.tracking.run_tracker import RunTracker
from tests.conftest import make_clip


def test_outer_phases_have_one_stable_monotonic_order() -> None:
    phases = list(OperationalPhase)

    assert phases == [
        OperationalPhase.DISCOVERY,
        OperationalPhase.DOWNLOAD,
        OperationalPhase.ANALYSIS,
        OperationalPhase.SELECTION,
        OperationalPhase.RENDER,
        OperationalPhase.MUSIC,
        OperationalPhase.DELIVERY,
        OperationalPhase.COMPLETE,
    ]
    assert [phase.order for phase in phases] == list(range(8))


def test_zero_work_phase_is_still_a_named_event() -> None:
    event = PhaseEvent(
        phase=OperationalPhase.DOWNLOAD,
        current=0,
        total=0,
        message="Downloads already cached",
        elapsed_seconds=0.0,
    )

    assert event.to_dict() == {
        "phase": "download",
        "label": "Download",
        "current": 0,
        "total": 0,
        "message": "Downloads already cached",
        "elapsed_seconds": 0.0,
    }


def _event(phase: OperationalPhase, message: str | None = None) -> PhaseEvent:
    return PhaseEvent(phase, 0, 0, message or phase.label, 0.0)


def test_run_phase_update_is_monotonic_and_mirrors_exact_attempt(tmp_path: Path) -> None:
    state = AutomationStateStore()
    attempt = state.start_attempt("daily wake")
    tracker = RunTracker("phase-run", capture_system=False)
    tracker.start_run(automation_attempt_id=attempt.id, source="auto")

    assert tracker.record_phase_event(_event(OperationalPhase.RENDER)) is True
    assert tracker.record_phase_event(_event(OperationalPhase.ANALYSIS)) is False
    tracker.fail_run("encoder failed")

    run = tracker.db.get_run("phase-run")
    persisted_attempt = state.get_last_attempt()
    assert run is not None
    assert run.status == "failed"
    assert run.last_phase is OperationalPhase.RENDER
    assert persisted_attempt is not None
    assert persisted_attempt.last_phase is OperationalPhase.RENDER


def test_editorial_failure_retains_attempt_phase_without_creating_run(tmp_path: Path) -> None:
    from unittest.mock import MagicMock, patch

    from immich_memories.cli._pipeline_runner import run_pipeline_and_generate
    from immich_memories.timeperiod import DateRange

    config = Config(
        cache={
            "database": str(tmp_path / "analysis-failure.db"),
            "directory": str(tmp_path / "cache"),
        }
    )
    state = AutomationStateStore()
    attempt = state.start_attempt("daily wake")
    clip = make_clip("asset-1", file_created_at=datetime(2026, 1, 1))

    # WHY: runtime construction owns annotation stores and model clients; fake the outer route.
    with (
        patch("immich_memories.analysis.editorial_runtime.build_smart_pipeline") as build_pipeline,
        pytest.raises(RuntimeError, match="editorial selection exploded"),
    ):
        build_pipeline.return_value.run_editorial_source.side_effect = RuntimeError(
            "editorial selection exploded"
        )
        run_pipeline_and_generate(
            assets=[clip.asset],
            client=MagicMock(),
            config=config,
            progress=MagicMock(),
            duration=60,
            transition="cut",
            music=None,
            output_path=tmp_path / "memory.mp4",
            memory_type="trip",
            person_names=[],
            date_range=DateRange(
                start=datetime(2026, 1, 1),
                end=datetime(2026, 1, 2),
            ),
            upload_to_immich=False,
            album=None,
            source="auto",
            automation_attempt_id=attempt.id,
        )

    persisted = state.get_last_attempt()
    assert persisted is not None
    assert persisted.last_phase is OperationalPhase.SELECTION
    build_pipeline.return_value.run_editorial_source.assert_called_once()
    assert RunTracker("unused").db.list_runs() == []


def test_run_continues_when_phase_database_write_fails(tmp_path: Path, monkeypatch) -> None:
    tracker = RunTracker("telemetry-failure", capture_system=False)
    tracker.start_run()

    def fail_write(*_args) -> bool:
        raise OperationalError("UPDATE pipeline_runs", {}, Exception("database is busy"))

    monkeypatch.setattr(tracker.db, "update_operational_phase", fail_write)

    assert tracker.record_phase_event(_event(OperationalPhase.RENDER)) is False
    assert tracker.db.get_run(tracker.run_id).status == "running"  # type: ignore[union-attr]


def test_editorial_continues_when_attempt_phase_write_fails(tmp_path: Path) -> None:
    from unittest.mock import MagicMock, patch

    from immich_memories.cli._pipeline_runner import run_pipeline_and_generate
    from immich_memories.timeperiod import DateRange

    config = Config(
        cache={
            "database": str(tmp_path / "telemetry.db"),
            "directory": str(tmp_path / "cache"),
        }
    )
    state = AutomationStateStore()
    attempt = state.start_attempt("daily wake")
    clip = make_clip("asset-1", file_created_at=datetime(2026, 1, 1))
    result = PipelineResult(
        selected_clips=[clip],
        clip_segments={clip.asset.id: (0.0, 4.0)},
        errors=[],
        stats={"selection_route": "editorial-source"},
    )
    output = tmp_path / "memory.mp4"

    # WHY: runtime construction owns annotation stores and model clients; fake the outer route.
    with (
        patch("immich_memories.analysis.editorial_runtime.build_smart_pipeline") as build_pipeline,
        # WHY: generation downloads media and invokes FFmpeg; inspect the handoff only.
        patch("immich_memories.generate.generate_memory", return_value=output) as generate,
        # WHY: force the durable telemetry write to fail without changing selection or rendering.
        patch.object(
            AutomationStateStore,
            "update_phase",
            side_effect=OperationalError("UPDATE automation_attempts", {}, Exception("busy")),
        ) as update_phase,
    ):
        candidate = ClipWithSegment(clip=clip, start_time=0.0, end_time=4.0, score=0.5)
        build_pipeline.return_value.run_editorial_source.return_value = ([candidate], result)
        actual, _, _ = run_pipeline_and_generate(
            assets=[clip.asset],
            client=MagicMock(),
            config=config,
            progress=MagicMock(),
            duration=60,
            transition="cut",
            music=None,
            output_path=output,
            memory_type="trip",
            person_names=[],
            date_range=DateRange(
                start=datetime(2026, 1, 1),
                end=datetime(2026, 1, 2),
            ),
            upload_to_immich=False,
            album=None,
            source="auto",
            automation_attempt_id=attempt.id,
        )

    assert actual == output
    build_pipeline.return_value.run_editorial_source.assert_called_once()
    assert update_phase.call_count > 0
    generate.assert_called_once()
    assert generate.call_args.args[0].clips == [clip]
    assert generate.call_args.args[0].completed_operational_phase is OperationalPhase.SELECTION
