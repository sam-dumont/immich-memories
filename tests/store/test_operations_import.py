"""The one-time import of operations history from cache.db, the run index and special-days.json."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pytest

from immich_memories.automation.catalogue import load_catalogue
from immich_memories.automation.notification_state import (
    NotificationFailureCategory,
    NotificationStateStore,
)
from immich_memories.automation.state_store import AutomationStateStore
from immich_memories.cache.asset_score_cache import AssetScoreCache
from immich_memories.cache.database import VideoAnalysisCache
from immich_memories.config_loader import Config, set_config
from immich_memories.operations.run_index import attempt_dir_for_run
from immich_memories.operations.store_import import import_legacy
from immich_memories.tracking.models import DeliveryStatus, RunMetadata
from immich_memories.tracking.run_database import RunDatabase

CATALOGUE = [
    {"day": "2018-04-21", "title": "A garden party", "photos": 88, "prompt_version": "v3"},
    {"scanned": 2018},
]


@pytest.fixture
def home(tmp_path) -> Path:
    """A legacy `~/.immich-memories` whose config keeps the default cache locations."""
    config = Config()
    config.cache.database = "~/.immich-memories/cache.db"
    config.cache.directory = "~/.immich-memories/cache"
    set_config(config)
    yield tmp_path
    set_config(None)


def _legacy_cache_db(path: Path) -> None:
    """A cache.db the pre-store app wrote: its own migration ladder, then synthetic rows."""
    VideoAnalysisCache(path)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(
            """INSERT INTO pipeline_runs (run_id, created_at, completed_at, status, memory_type,
               memory_key, memory_people_json, source, automation_attempt_id, person_name,
               date_range_start, date_range_end, target_duration_seconds, output_path,
               output_size_bytes, delivery_status, delivery_attempts, immich_asset_id,
               warnings_json, llm_metrics, system_info, phase_events, last_phase)
               VALUES ('20240301_080000_ab12', '2024-03-01T08:00:00+01:00',
               '2024-03-01T08:20:00+00:00', 'completed', 'trip', 'trip:2024-02:coast',
               '["sam example"]', 'auto', 'attempt-1', 'Sam Example', '2024-02-01',
               '2024-02-10', 120, '/films/coast.mp4', 1234, 'delivered', 1, 'asset-9',
               '["music fell back"]', '{"calls": 3}', '{"platform": "linux"}',
               '[{"phase": "render"}]', 'render')"""
        )
        conn.execute(
            """INSERT INTO pipeline_runs (run_id, created_at, status)
               VALUES ('20240302_080000_cd34', '2024-03-02T08:00:00', 'failed')"""
        )
        conn.execute(
            """INSERT INTO phase_stats (run_id, phase_name, started_at, duration_seconds, errors)
               VALUES ('20240301_080000_ab12', 'assembly', '2024-03-01T07:05:00+00:00', 42.5,
               '["one"]')"""
        )
        conn.executemany(
            """INSERT INTO automation_attempts (id, started_at, finished_at, outcome, reason,
               memory_key, run_id) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                ("attempt-0", "2024-02-28T06:00:00+00:00", "2024-02-28T06:01:00+00:00",
                 "failed", "render failed", "trip:2024-02:coast", None),
                ("attempt-1", "2024-03-01T07:00:00+00:00", "2024-03-01T08:21:00+00:00",
                 "completed", "generated", "trip:2024-02:coast", "20240301_080000_ab12"),
            ],
        )  # fmt: skip
        conn.execute(
            """INSERT INTO notification_health (id, last_attempt_at, last_failure_at,
               failure_category, failure_message) VALUES (1, '2024-03-01T09:00:00+00:00',
               '2024-03-01T09:00:00+00:00', 'quota', 'quota reached')"""
        )
        conn.execute(
            """INSERT INTO asset_scores (asset_id, asset_type, metadata_score, combined_score,
               llm_interest, analyzed_at, model_version)
               VALUES ('asset-1', 'video', 0.3, 0.6, 0.8, '2024-03-01 07:30:00', 'v2')"""
        )
        conn.commit()


def _legacy_home(home: Path, attempt_dir: Path) -> None:
    _legacy_cache_db(home / "cache.db")
    index = home / "cache" / "editorial-runs" / "by-run"
    index.mkdir(parents=True)
    (index / "20240301_080000_ab12.json").write_text(
        json.dumps(
            {
                "run_id": "20240301_080000_ab12",
                "attempt_dir": str(attempt_dir),
                "output_path": "/films/coast.mp4",
            }
        )
    )
    (index / "broken.json").write_text("{")
    (home / "special-days.json").write_text(json.dumps(CATALOGUE))


def test_the_import_carries_every_record_and_identity_exactly(store, home, tmp_path):
    attempt_dir = tmp_path / "attempt"
    attempt_dir.mkdir()
    _legacy_home(home, attempt_dir)
    before = (home / "cache.db").read_bytes()

    outcome = import_legacy(store, home)

    runs = RunDatabase(store)
    run = runs.get_run("20240301_080000_ab12")
    assert run.created_at == datetime(2024, 3, 1, 7, 0, tzinfo=UTC)
    assert (run.memory_key, run.memory_people, run.source) == (
        "trip:2024-02:coast",
        ("sam example",),
        "auto",
    )
    assert (run.delivery_status, run.immich_asset_id) == (DeliveryStatus.DELIVERED, "asset-9")
    assert run.warnings == ["music fell back"]
    assert run.llm_metrics == {"calls": 3}
    assert run.system_info.platform == "linux"
    assert [(p.phase_name, p.duration_seconds, p.errors) for p in run.phases] == [
        ("assembly", 42.5, ["one"])
    ]
    assert runs.get_run("20240302_080000_cd34").target_duration_seconds == 600
    assert runs.get_generated_memory_keys() == {"trip:2024-02:coast"}
    attempts = AutomationStateStore(store)
    assert attempts.get_last_attempt().id == "attempt-1"
    assert attempts.consecutive_failures_by_key() == {}
    health = NotificationStateStore(store).get()
    assert health.failure_category is NotificationFailureCategory.QUOTA
    (score,) = AssetScoreCache(store).all_scores()
    assert (score["asset_id"], score["model_version"], score["llm_interest"]) == (
        "asset-1",
        "v2",
        0.8,
    )
    assert attempt_dir_for_run("20240301_080000_ab12", store=store) == attempt_dir
    assert load_catalogue(store) == CATALOGUE
    # 2 runs + 1 phase + 2 attempts + 1 health + 1 score + 1 index record + 2 catalogue rows
    assert (outcome.imported, outcome.skipped) == (10, 1)
    assert (home / "cache.db").read_bytes() == before


def test_a_second_import_changes_nothing(store, home, tmp_path):
    _legacy_home(home, tmp_path)
    import_legacy(store, home)

    again = import_legacy(store, home)

    assert again.imported == 0
    assert len(RunDatabase(store).list_runs()) == 2
    assert len(RunDatabase(store).get_run("20240301_080000_ab12").phases) == 1


def test_a_legacy_row_never_replaces_what_the_store_holds(store, home, tmp_path):
    _legacy_home(home, tmp_path)
    RunDatabase(store).save_run(
        RunMetadata(
            run_id="20240301_080000_ab12",
            created_at=datetime(2025, 1, 1, tzinfo=UTC),
            status="failed",
        )
    )
    NotificationStateStore(store).record_success(now=datetime(2025, 1, 2, tzinfo=UTC))

    import_legacy(store, home)

    kept = RunDatabase(store).get_run("20240301_080000_ab12")
    assert (kept.status, kept.phases) == ("failed", [])
    assert NotificationStateStore(store).get().failure_category is None


def test_a_relocated_cache_db_is_read_where_the_config_puts_it(store, home, tmp_path):
    elsewhere = tmp_path / "elsewhere" / "analysis.db"
    elsewhere.parent.mkdir()
    _legacy_cache_db(elsewhere)
    config = Config()
    config.cache.database = str(elsewhere)
    config.cache.directory = "~/.immich-memories/cache"
    set_config(config)

    outcome = import_legacy(store, home)

    assert RunDatabase(store).get_run("20240302_080000_cd34") is not None
    assert "no special-days.json" in outcome.notes


def test_nothing_to_import_is_not_an_error(store, home):
    outcome = import_legacy(store, home)

    assert (outcome.imported, outcome.skipped) == (0, 0)
    assert set(outcome.notes) == {"no cache.db", "no run index", "no special-days.json"}
