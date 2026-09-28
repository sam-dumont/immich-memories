"""Run history in the store: what the runs page, `runs` CLI and automation dedup read."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from immich_memories.automation.state_store import AutomationStateStore
from immich_memories.automation.status import is_within_cooldown
from immich_memories.operations.phases import OperationalPhase, PhaseEvent
from immich_memories.operations.run_index import attempt_dir_for_run, record_run_attempt
from immich_memories.tracking.models import DeliveryStatus, PhaseStats, RunMetadata
from immich_memories.tracking.run_database import RunDatabase
from immich_memories.tracking.run_lifecycle_errors import (
    DuplicateRunError,
    InvalidRunLifecycleError,
)

_T0 = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


def _run(run_id: str, minutes: int = 0, **fields) -> RunMetadata:
    return RunMetadata(run_id=run_id, created_at=_T0 + timedelta(minutes=minutes), **fields)


def test_a_run_comes_back_as_it_was_saved(store):
    db = RunDatabase(store)
    saved = _run(
        "run-a",
        memory_type="monthly_highlights",
        memory_key="monthly:2026-02",
        memory_people=("Alex  Example",),
        source="auto",
        date_range_start=date(2026, 2, 1),
        date_range_end=date(2026, 2, 28),
        target_duration_seconds=90,
        warnings=["short"],
    )
    db.save_run(saved)
    db.save_phase_stats("run-a", PhaseStats("assembly", _T0, _T0, 4.5, 3, 3, ["x"], {"k": 1}))

    run = db.get_run("run-a")

    assert run is not None
    assert run.created_at == _T0
    assert run.memory_people == ("alex example",)
    assert (run.date_range_start, run.target_duration_seconds) == (date(2026, 2, 1), 90)
    assert run.warnings == ["short"]
    assert [(p.phase_name, p.errors, p.extra_metrics) for p in run.phases] == [
        ("assembly", ["x"], {"k": 1})
    ]


def test_a_run_id_is_claimed_once(store):
    db = RunDatabase(store)
    db.save_run(_run("run-a", status="completed"))

    with pytest.raises(DuplicateRunError):
        db.save_run(_run("run-a"))
    assert db.get_run("run-a").status == "completed"


def test_runs_list_newest_first_with_filters(store):
    db = RunDatabase(store)
    db.save_run(_run("old", 0, person_name="Alex", source="auto", status="completed"))
    db.save_run(_run("mid", 10, source="manual", status="failed"))
    db.save_run(_run("new", 20, person_name="Alex", source="auto", status="completed"))

    assert [r.run_id for r in db.list_runs()] == ["new", "mid", "old"]
    assert [r.run_id for r in db.list_runs(limit=1, offset=1)] == ["mid"]
    assert [r.run_id for r in db.list_runs(person_name="Alex")] == ["new", "old"]
    assert [r.run_id for r in db.list_runs(status="failed")] == ["mid"]
    assert [r.run_id for r in db.list_runs(source="auto", status="completed")] == ["new", "old"]


def test_completion_order_ranks_by_when_a_run_finished(store):
    db = RunDatabase(store)
    db.save_run(_run("started-first", 0, status="completed", completed_at=_T0 + timedelta(hours=5)))
    db.save_run(
        _run("started-later", 30, status="completed", completed_at=_T0 + timedelta(hours=1))
    )

    ordered = db.list_runs(status="completed", order_by_completion=True)

    assert [r.run_id for r in ordered] == ["started-first", "started-later"]
    assert db.get_last_run_of_type("monthly_highlights") is None
    with pytest.raises(ValueError, match="order_by_completion"):
        db.list_runs(order_by_completion=True)


def test_delivery_lifecycle_moves_only_forward(store, tmp_path):
    db = RunDatabase(store)
    db.save_run(_run("run-a"))
    film = tmp_path / "film.mp4"
    film.write_bytes(b"x")

    completed = db.complete_artifact(
        "run-a",
        completed_at=_T0,
        output_path=str(film),
        output_size_bytes=5_000_000_000,
        output_duration_seconds=61.0,
        delivery_requested=True,
        delivery_album="Memories",
        warnings=[],
        clips_analyzed=10,
        clips_selected=4,
        errors_count=0,
    )
    assert completed.delivery_status is DeliveryStatus.PENDING
    assert completed.output_size_bytes == 5_000_000_000
    assert db.count_pending_deliveries(source="manual") == 1
    assert db.get_oldest_pending_delivery("manual").run_id == "run-a"

    pending = db.mark_delivery_pending("run-a", "timeout")
    delivered = db.mark_delivered("run-a", " asset-1 ")

    assert pending.delivery_attempts == 1
    assert (delivered.delivery_status, delivered.delivery_attempts) == (DeliveryStatus.DELIVERED, 2)
    assert db.delivered_asset_ids() == frozenset({"asset-1"})
    with pytest.raises(InvalidRunLifecycleError, match="requested delivery"):
        db.mark_delivered("run-a", "asset-2")
    with pytest.raises(InvalidRunLifecycleError, match="running run"):
        db.complete_artifact(
            "run-a",
            completed_at=_T0,
            output_path=str(film),
            output_size_bytes=1,
            output_duration_seconds=1.0,
            delivery_requested=False,
            delivery_album=None,
            warnings=[],
            clips_analyzed=1,
            clips_selected=1,
            errors_count=0,
        )
    with pytest.raises(KeyError):
        db.mark_delivery_abandoned("missing", "gone")


def test_a_run_phase_never_goes_back_and_mirrors_its_attempt(store):
    attempts = AutomationStateStore(store)
    attempt = attempts.start_attempt("daily wake")
    db = RunDatabase(store)
    db.save_run(_run("run-a", automation_attempt_id=attempt.id))
    later = PhaseEvent(OperationalPhase.RENDER, 1, 2, "rendering", 0.5)
    earlier = PhaseEvent(OperationalPhase.DISCOVERY, 0, 0, "discovering", 0.0)

    assert db.update_operational_phase("run-a", later) is True
    assert db.update_operational_phase("run-a", earlier) is False

    run = db.get_run("run-a")
    mirrored = attempts.get_attempt(attempt.id)
    assert run.last_phase is OperationalPhase.RENDER
    assert run.phase_events == [later.to_dict()]
    assert mirrored.last_phase is OperationalPhase.RENDER
    with pytest.raises(KeyError):
        db.update_operational_phase("missing", later)


def test_cooldown_and_dedup_read_the_completed_auto_history(store):
    db = RunDatabase(store)
    recent = datetime.now(tz=UTC) - timedelta(hours=2)
    # A made memory is a film: a cut kept without one (`generate --no-render`) is not.
    db.save_run(
        _run(
            "manual",
            status="completed",
            memory_key="trip:a",
            completed_at=recent,
            output_path="/films/trip-a.mp4",
        )
    )
    db.save_run(_run("failed", status="failed", memory_key="trip:b", source="auto"))

    assert is_within_cooldown(db, 24) is False
    assert db.get_generated_memory_keys() == {"trip:a"}

    db.save_run(
        RunMetadata(
            run_id="auto",
            created_at=recent,
            completed_at=recent,
            status="completed",
            memory_key="year:2025",
            source="auto",
            output_path="/films/year-2025.mp4",
        )
    )

    assert is_within_cooldown(db, 24) is True
    assert is_within_cooldown(db, 1) is False
    assert db.get_generated_memory_keys() == {"trip:a", "year:2025"}


def test_deleting_a_run_takes_its_phase_timings_and_stats_follow(store):
    db = RunDatabase(store)
    db.save_run(_run("a", status="completed", clips_selected=4))
    db.save_run(_run("b", 5, status="failed", clips_selected=2))
    db.save_phase_stats("a", PhaseStats("assembly", _T0, duration_seconds=3.0))
    db.save_phase_stats("a", PhaseStats("music", _T0, duration_seconds=1.0))
    db.save_phase_stats("gone", PhaseStats("orphan", _T0, duration_seconds=9.0))

    stats = db.get_aggregate_stats()

    assert (stats["total_runs"], stats["completed_runs"], stats["failed_runs"]) == (2, 1, 1)
    assert (stats["total_processing_seconds"], stats["avg_run_seconds"]) == (4.0, 4.0)
    assert stats["avg_clips"] == 3.0
    assert db.delete_run("a") is True
    assert db.get_run("a") is None
    assert db.get_aggregate_stats()["total_processing_seconds"] == 0


def test_the_run_index_resolves_a_run_to_its_attempt(store, tmp_path):
    attempt = tmp_path / "attempt"
    attempt.mkdir()

    record_run_attempt("run-a", attempt, tmp_path / "film.mp4", store=store)

    assert attempt_dir_for_run("run-a", store=store) == attempt
    assert attempt_dir_for_run("run-b", store=store) is None
    assert (attempt / "run.private.json").is_file()


def test_a_free_form_run_label_of_any_length_is_kept(store):
    # A real history held a 43-character `source` label; SQLite never enforced the old
    # VARCHAR(32), so only PostgreSQL refused it, halfway through an import.
    db = RunDatabase(store)
    label = "owner-reviewed-" + "matrix-render-corrected-gift-" * 8

    db.save_run(_run("run-long", source=label, memory_key="k:" + "x" * 900))

    run = db.get_run("run-long")
    assert run is not None
    assert run.source == label
    assert run.memory_key == "k:" + "x" * 900
