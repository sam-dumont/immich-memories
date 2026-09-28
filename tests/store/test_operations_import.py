"""The one-time import of operations history from cache.db, the run index and special-days.json."""

from __future__ import annotations

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
from immich_memories.config_loader import Config, set_config
from immich_memories.operations.run_index import attempt_dir_for_run
from immich_memories.operations.store_import import import_legacy
from immich_memories.tracking.models import DeliveryStatus, RunMetadata
from immich_memories.tracking.run_database import RunDatabase
from tests.legacy_cache_db import write_legacy_cache_db

from .legacy_home import CATALOGUE, write_history_cache_db, write_operations_home


@pytest.fixture
def home(tmp_path) -> Path:
    """A legacy `~/.immich-memories` whose config keeps the default cache locations."""
    config = Config()
    config.cache.database = "~/.immich-memories/cache.db"
    config.cache.directory = "~/.immich-memories/cache"
    set_config(config)
    yield tmp_path
    set_config(None)


def test_the_import_carries_every_record_and_identity_exactly(store, home, tmp_path):
    attempt_dir = tmp_path / "attempt"
    attempt_dir.mkdir()
    write_operations_home(home, attempt_dir)
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
    write_operations_home(home, tmp_path)
    import_legacy(store, home)

    again = import_legacy(store, home)

    assert again.imported == 0
    assert len(RunDatabase(store).list_runs()) == 2
    assert len(RunDatabase(store).get_run("20240301_080000_ab12").phases) == 1


def test_a_legacy_row_never_replaces_what_the_store_holds(store, home, tmp_path):
    write_operations_home(home, tmp_path)
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
    write_history_cache_db(elsewhere)
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


def test_a_score_banked_before_versions_is_found_under_the_empty_version(store, home):
    legacy = write_legacy_cache_db(home / "cache.db", version=21)
    with closing(sqlite3.connect(legacy)) as conn:
        conn.executemany(
            "INSERT INTO asset_scores (asset_id, asset_type, metadata_score, combined_score,"
            " model_version) VALUES (?, 'photo', 0.5, ?, ?)",
            [("current", 0.81, "qwen#look2"), ("unversioned", 0.43, None)],
        )
        conn.commit()

    import_legacy(store, home)

    served = {
        (s["asset_id"], s["model_version"]): s["combined_score"]
        for s in AssetScoreCache(store).all_scores()
    }
    assert served == {("current", "qwen#look2"): 0.81, ("unversioned", ""): 0.43}
