"""Tests for RunDatabase FK constraint handling when run_id is missing."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from immich_memories.config_loader import Config, set_config
from immich_memories.db import open_store
from immich_memories.operations.store_import import import_legacy
from immich_memories.tracking.models import PhaseStats, RunMetadata
from immich_memories.tracking.run_database import RunDatabase
from immich_memories.tracking.run_tracker import RunTracker
from tests.legacy_cache_db import write_legacy_cache_db


@pytest.fixture
def db(tmp_path):
    return RunDatabase()


def _import_into_the_store(db_path: Path, home: Path) -> None:
    """The one-time upgrade: a legacy cache.db's history moves into this test's store."""
    set_config(Config(cache={"database": str(db_path), "directory": str(home / "cache")}))
    import_legacy(open_store(), home)


def _make_phase_stats() -> PhaseStats:
    return PhaseStats(
        phase_name="analysis",
        started_at=datetime(2026, 3, 27, 10, 0, tzinfo=UTC),
        completed_at=datetime(2026, 3, 27, 10, 5, tzinfo=UTC),
        duration_seconds=300.0,
        items_processed=42,
        items_total=42,
        errors=[],
        extra_metrics={},
    )


class TestCompletePhaseDBResilience:
    """RunTracker.complete_phase must not crash when DB write fails."""

    # WHY: RunDatabase opens a SQLite connection — isolate tracker logic from disk I/O
    @patch("immich_memories.tracking.run_tracker.RunDatabase")
    def test_complete_phase_survives_db_exception(self, mock_db_cls, caplog):
        """complete_phase logs a warning and continues if DB raises any exception."""
        tracker = RunTracker()
        tracker.start_run()
        tracker.start_phase("analysis", total_items=10)

        # Simulate DB failure (e.g. DB deleted, corruption, etc.)
        tracker.db.save_phase_stats.side_effect = RuntimeError("disk I/O error")

        with caplog.at_level(logging.WARNING):
            tracker.complete_phase(items_processed=10)

        # Phase state should be reset even after failure
        assert tracker._current_phase is None
        assert any("phase stats" in r.message.lower() for r in caplog.records)


class TestSavePhaseStatsFKConstraint:
    """save_phase_stats must not crash when run_id is missing from pipeline_runs."""

    def test_nonexistent_run_id_does_not_raise(self, db):
        """Inserting phase stats for a missing run_id logs a warning instead of raising."""
        stats = _make_phase_stats()
        # Should NOT raise sqlite3.IntegrityError
        db.save_phase_stats("nonexistent_run_id", stats)

    def test_nonexistent_run_id_logs_warning(self, db, caplog):
        """A warning is logged when phase stats are lost due to missing run_id."""
        stats = _make_phase_stats()
        with caplog.at_level(logging.WARNING):
            db.save_phase_stats("nonexistent_run_id", stats)
        assert any("run_id" in record.message.lower() for record in caplog.records)

    def test_valid_run_id_saves_normally(self, db):
        """Phase stats with a valid run_id are saved successfully."""
        run = RunMetadata(
            run_id="valid_run_001",
            created_at=datetime(2026, 3, 27, 10, 0, tzinfo=UTC),
            status="running",
        )
        db.save_run(run)

        stats = _make_phase_stats()
        db.save_phase_stats("valid_run_001", stats)

        # Verify the stats were actually persisted
        retrieved = db.get_run("valid_run_001").phases
        assert len(retrieved) == 1
        assert retrieved[0].phase_name == "analysis"


def _make_completed_run(
    run_id: str,
    created_at: datetime,
    *,
    memory_key: str = "trip:key",
    source: str = "auto",
) -> RunMetadata:
    return RunMetadata(
        run_id=run_id,
        created_at=created_at,
        completed_at=created_at + timedelta(minutes=10),
        status="completed",
        memory_type="trip",
        memory_key=memory_key,
        source=source,
    )


def test_a_populated_v9_database_imports_without_losing_rows(tmp_path: Path) -> None:
    """Production-era v9 run records reach the store intact."""
    db_path = write_legacy_cache_db(tmp_path / "v9.db", version=9)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO pipeline_runs (
                run_id, created_at, completed_at, status,
                memory_type, memory_key, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "existing-v9",
                "2026-07-01T09:00:00",
                "2026-07-01T09:10:00",
                "completed",
                "trip",
                "trip:key",
                "auto",
            ),
        )

    _import_into_the_store(db_path, tmp_path)
    loaded = RunDatabase().get_run("existing-v9")

    assert loaded is not None
    assert loaded.memory_key == "trip:key"
    # What v11 back-fills on a completed auto run reaches the store the same way.
    assert loaded.memory_category == "trip"
    assert loaded.memory_people == ()


def test_a_populated_v11_database_imports_without_losing_runs(tmp_path: Path) -> None:
    """Rows written before automation attempts had ids keep their identity in the store."""
    db_path = write_legacy_cache_db(tmp_path / "v11.db", version=11)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO pipeline_runs (
                run_id, created_at, completed_at, status,
                memory_type, memory_key, memory_category, memory_people_json, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "existing-v11",
                "2026-07-02T09:00:00+00:00",
                "2026-07-02T09:01:00+00:00",
                "completed",
                "trip",
                "trip:key",
                "trip",
                "[]",
                "auto",
            ),
        )
        conn.commit()

    _import_into_the_store(db_path, tmp_path)
    loaded = RunDatabase().get_run("existing-v11")

    assert loaded is not None
    assert loaded.run_id == "existing-v11"
    assert loaded.automation_attempt_id is None


def test_run_identity_fields_round_trip_with_normalized_people(db: RunDatabase) -> None:
    """Run identity persists category and canonical Unicode person names."""
    run = _make_completed_run("normalized", datetime(2026, 7, 2, 9, 0, tzinfo=UTC))
    run.memory_category = "person_spotlight"
    run.memory_people = ("  ADA\tSmith ", "Straße   Example")
    run.automation_attempt_id = "attempt-round-trip"
    db.save_run(run)

    loaded = db.get_run("normalized")
    assert loaded is not None
    assert loaded.memory_category == "person_spotlight"
    assert loaded.memory_people == ("ada smith", "strasse example")
    assert loaded.automation_attempt_id == "attempt-round-trip"
    assert loaded.to_dict()["memory_people"] == ["ada smith", "strasse example"]
    assert RunMetadata.from_dict(json.loads(loaded.to_json())).memory_people == (
        "ada smith",
        "strasse example",
    )


def test_list_runs_filters_source_before_limit(db: RunDatabase) -> None:
    """A newer manual run cannot hide an older automation run behind LIMIT."""
    db.save_run(_make_completed_run("auto", datetime(2026, 7, 2, 9, 0, tzinfo=UTC), source="auto"))
    db.save_run(
        _make_completed_run("manual", datetime(2026, 7, 3, 9, 0, tzinfo=UTC), source="manual")
    )

    runs = db.list_runs(limit=1, status="completed", source="auto")

    assert [run.run_id for run in runs] == ["auto"]


def test_list_runs_treats_empty_source_as_a_concrete_filter(db: RunDatabase) -> None:
    """Only None disables source filtering; an empty string remains queryable."""
    db.save_run(_make_completed_run("empty", datetime(2026, 7, 2, 9, 0, tzinfo=UTC), source=""))
    db.save_run(
        _make_completed_run("manual", datetime(2026, 7, 3, 9, 0, tzinfo=UTC), source="manual")
    )

    runs = db.list_runs(status="completed", source="")

    assert [run.run_id for run in runs] == ["empty"]


def test_list_runs_can_order_completed_rows_by_completion_time(db: RunDatabase) -> None:
    """Automation recency follows completion, with legacy rows falling back to creation."""
    completed_first = _make_completed_run(
        "created-last-completed-first",
        datetime(2026, 8, 10, 10, 0, tzinfo=UTC),
    )
    completed_first.completed_at = datetime(2026, 8, 10, 10, 30, tzinfo=UTC)
    legacy = _make_completed_run(
        "legacy-null-completion", datetime(2026, 8, 10, 11, 30, tzinfo=UTC)
    )
    legacy.completed_at = None
    completed_last = _make_completed_run(
        "created-first-completed-last",
        datetime(2026, 8, 10, 9, 0, tzinfo=UTC),
    )
    completed_last.completed_at = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    for run in (completed_first, legacy, completed_last):
        db.save_run(run)

    runs = db.list_runs(
        status="completed",
        source="auto",
        order_by_completion=True,
    )

    assert [run.run_id for run in runs] == [
        "created-first-completed-last",
        "legacy-null-completion",
        "created-last-completed-first",
    ]


def test_completion_order_has_deterministic_tie_breakers(db: RunDatabase) -> None:
    """Equal completion and creation timestamps fall back to descending run ID."""
    created_at = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)
    for run_id in ("tie-a", "tie-z"):
        run = _make_completed_run(run_id, created_at)
        db.save_run(run)

    runs = db.list_runs(
        status="completed",
        source="auto",
        order_by_completion=True,
    )

    assert [run.run_id for run in runs] == ["tie-z", "tie-a"]


def test_last_run_of_type_filters_source_before_order_and_limit(db: RunDatabase) -> None:
    """A newer manual run cannot hide the last auto run of the same memory type."""
    completed_last = _make_completed_run(
        "created-first-completed-last",
        datetime(2026, 8, 8, 9, 0, tzinfo=UTC),
        source="auto",
    )
    completed_last.completed_at = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    db.save_run(completed_last)
    db.save_run(
        _make_completed_run("created-last", datetime(2026, 8, 9, 9, 0, tzinfo=UTC), source="auto")
    )
    db.save_run(
        _make_completed_run(
            "newer-manual-trip",
            datetime(2026, 8, 10, 9, 0, tzinfo=UTC),
            source="manual",
        )
    )

    run = db.get_last_run_of_type("trip", source="auto")

    assert run is not None
    assert run.run_id == "created-first-completed-last"


def test_completed_automation_attempt_identity_is_exact(db: RunDatabase) -> None:
    """A same-key completion from another wake cannot satisfy this parent attempt."""
    wrong = _make_completed_run("wrong-attempt", datetime(2026, 7, 2, 9, 0, tzinfo=UTC))
    wrong.automation_attempt_id = "attempt-other"
    expected = _make_completed_run("exact-attempt", datetime(2026, 7, 2, 9, 1, tzinfo=UTC))
    expected.automation_attempt_id = "attempt-exact"
    db.save_run(wrong)
    db.save_run(expected)

    actual = db.get_completed_run_by_automation_attempt(
        "attempt-exact",
        memory_key="trip:key",
    )

    assert actual == expected
    assert (
        db.get_completed_run_by_automation_attempt(
            "attempt-other",
            memory_key="different:key",
        )
        is None
    )


def test_a_failed_automation_attempt_still_finds_the_run_it_started(db: RunDatabase) -> None:
    """A failed generation is exactly when its run record is worth reaching."""
    failed = RunMetadata(
        run_id="failed-child",
        created_at=datetime(2026, 7, 2, 9, 0, tzinfo=UTC),
        status="failed",
        memory_type="trip",
        memory_key="trip:key",
        source="auto",
    )
    failed.automation_attempt_id = "attempt-that-failed"
    db.save_run(failed)

    assert (
        db.get_completed_run_by_automation_attempt("attempt-that-failed", memory_key="trip:key")
        is None
    )
    assert db.get_run_by_automation_attempt("attempt-that-failed") == failed
    assert db.get_run_by_automation_attempt("attempt-never-started") is None


def test_completed_automation_attempt_identity_rejects_ambiguity(db: RunDatabase) -> None:
    """Two matching child rows are corruption, not a license to pick one."""
    first = _make_completed_run("duplicate-first", datetime(2026, 7, 2, 9, 0, tzinfo=UTC))
    first.automation_attempt_id = "attempt-duplicate"
    second = _make_completed_run("duplicate-second", datetime(2026, 7, 2, 9, 1, tzinfo=UTC))
    second.automation_attempt_id = "attempt-duplicate"
    db.save_run(first)
    db.save_run(second)

    with pytest.raises(RuntimeError, match="Multiple completed auto runs"):
        db.get_completed_run_by_automation_attempt(
            "attempt-duplicate",
            memory_key="trip:key",
        )


class TestTargetDurationSurvivesTheRoundTrip:
    """#411: a 25s target was stored as 25//60 = 0 minutes and read back as
    (0 or 10)*60 = 600 — run_metadata claimed the preset default for every
    sub-minute or non-round-minute run."""

    def test_a_sub_minute_target_is_preserved(self, tmp_path: Path) -> None:
        db = RunDatabase()
        run = RunMetadata(
            run_id="r-25s",
            created_at=datetime(2026, 8, 21, tzinfo=UTC),
            target_duration_seconds=25,
        )
        db.save_run(run)

        loaded = db.get_run("r-25s")

        assert loaded is not None
        assert loaded.target_duration_seconds == 25

    def test_a_pre_migration_row_backfills_from_minutes(self, tmp_path: Path) -> None:
        db_path = write_legacy_cache_db(tmp_path / "old.db", version=18)
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO pipeline_runs (run_id, created_at, status, target_duration_minutes)"
                " VALUES ('r-old', '2026-08-01', 'completed', 10)"
            )

        _import_into_the_store(db_path, tmp_path)
        loaded = RunDatabase().get_run("r-old")

        assert loaded is not None
        assert loaded.target_duration_seconds == 600
