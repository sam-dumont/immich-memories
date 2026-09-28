"""A `cache.db` as the app wrote it before the store: the history the legacy import reads.

The migration ladder that built these files is gone. What it left is frozen here: the
layout of its last step (v25) for the tables that moved to the store, and a
`schema_migrations` ledger claiming `version`. The analysis tables that sat beside them are
left out: nothing reads them any more. Below v22 `asset_scores` keeps its old single-asset
key, which could hold a NULL version.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

_HISTORY = """
CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (datetime('now')),
    description TEXT
);
CREATE TABLE pipeline_runs (
    run_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    person_name TEXT,
    person_id TEXT,
    date_range_start TEXT,
    date_range_end TEXT,
    target_duration_minutes INTEGER DEFAULT 10,
    output_path TEXT,
    output_size_bytes INTEGER DEFAULT 0,
    output_duration_seconds REAL DEFAULT 0.0,
    clips_analyzed INTEGER DEFAULT 0,
    clips_selected INTEGER DEFAULT 0,
    errors_count INTEGER DEFAULT 0,
    system_info TEXT,
    memory_type TEXT,
    memory_key TEXT,
    source TEXT DEFAULT 'manual',
    memory_category TEXT,
    memory_people_json TEXT NOT NULL DEFAULT '[]',
    automation_attempt_id TEXT,
    delivery_status TEXT NOT NULL DEFAULT 'not_requested',
    delivery_attempts INTEGER NOT NULL DEFAULT 0,
    delivery_error TEXT,
    immich_asset_id TEXT,
    delivery_album TEXT,
    warnings_json TEXT NOT NULL DEFAULT '[]',
    last_phase TEXT,
    target_duration_seconds INTEGER,
    llm_metrics TEXT,
    phase_events TEXT NOT NULL DEFAULT '[]',
    title_source TEXT
);
CREATE TABLE phase_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    phase_name TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    duration_seconds REAL DEFAULT 0.0,
    items_processed INTEGER DEFAULT 0,
    items_total INTEGER DEFAULT 0,
    errors TEXT,
    extra_metrics TEXT,
    FOREIGN KEY (run_id) REFERENCES pipeline_runs(run_id) ON DELETE CASCADE
);
CREATE TABLE automation_attempts (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    outcome TEXT NOT NULL,
    reason TEXT NOT NULL,
    candidate_category TEXT,
    memory_type TEXT,
    memory_key TEXT,
    run_id TEXT,
    error TEXT,
    last_phase TEXT,
    phase_events TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE notification_health (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    last_attempt_at TEXT,
    last_success_at TEXT,
    last_failure_at TEXT,
    failure_category TEXT,
    failure_message TEXT
);
"""

_SCORES_V22 = """
CREATE TABLE asset_scores (
    asset_id TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    llm_interest REAL,
    llm_quality REAL,
    llm_emotion TEXT,
    llm_description TEXT,
    llm_category TEXT,
    safe_cut_gaps TEXT,
    metadata_score REAL NOT NULL,
    combined_score REAL NOT NULL,
    analyzed_at TEXT NOT NULL DEFAULT (datetime('now')),
    model_version TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (asset_id, model_version)
);
"""

_SCORES_BEFORE_V22 = """
CREATE TABLE asset_scores (
    asset_id TEXT PRIMARY KEY,
    asset_type TEXT NOT NULL,
    llm_interest REAL,
    llm_quality REAL,
    llm_emotion TEXT,
    llm_description TEXT,
    llm_category TEXT,
    safe_cut_gaps TEXT,
    metadata_score REAL NOT NULL,
    combined_score REAL NOT NULL,
    analyzed_at TEXT NOT NULL DEFAULT (datetime('now')),
    model_version TEXT
);
"""


def write_legacy_cache_db(path: Path, version: int = 25) -> Path:
    """Create the pre-store `cache.db` at `path`, its ledger claiming `version`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(_HISTORY + (_SCORES_V22 if version >= 22 else _SCORES_BEFORE_V22))
        conn.executemany(
            "INSERT INTO schema_migrations (version, description) VALUES (?, ?)",
            [(step, f"Migration to v{step}") for step in range(1, version + 1)],
        )
        conn.commit()
    return path
