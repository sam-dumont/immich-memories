"""A whole legacy `~/.immich-memories`, as an install from before the store left it.

Every record is synthetic: invented people, made-up asset ids, no real places or dates of
birth. `write_legacy_home` lays out every file the legacy import reads.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

import sqlalchemy as sa
import yaml

from immich_memories.db import Store
from immich_memories.db.tables import metadata
from tests.legacy_cache_db import write_legacy_cache_db

from .legacy_annotation_files import WRITTEN, write_annotations, write_judgments
from .test_people_registry import LEGACY_DOCUMENT

CATALOGUE = [
    {"day": "2018-04-21", "title": "A garden party", "photos": 88, "prompt_version": "v3"},
    {"scanned": 2018},
]


def write_history_cache_db(path: Path) -> None:
    """A cache.db the pre-store app wrote: its own migration ladder, then synthetic rows."""
    write_legacy_cache_db(path)
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


def write_operations_home(home: Path, attempt_dir: Path) -> None:
    write_history_cache_db(home / "cache.db")
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


def write_legacy_home(home: Path, *, extra_descriptions: int = 0) -> Path:
    """Every legacy file under `home`; `extra_descriptions` pads annotations.sqlite so an
    import of it takes several batches."""
    home.mkdir(parents=True, exist_ok=True)
    (home / "people.yaml").write_text(yaml.dump(LEGACY_DOCUMENT, sort_keys=False))
    attempt_dir = home / "attempts" / "20240301_080000_ab12"
    attempt_dir.mkdir(parents=True)
    write_operations_home(home, attempt_dir)
    annotations = write_annotations(home / "cache" / "annotations.sqlite")
    write_judgments(home / "cache" / "judgments.db")
    with closing(sqlite3.connect(annotations)) as legacy, legacy:
        legacy.executemany(
            "INSERT INTO descriptions VALUES (?, 'smolvlm', ?, 'compact', ?)",
            [(f"pad-{n:05d}", f"Picture {n}.", WRITTEN) for n in range(extra_descriptions)],
        )
    return home


def snapshot(home: Path) -> dict[str, tuple[bytes, int]]:
    """Every file under `home` with its bytes and mtime, to prove nothing was touched."""
    return {
        str(path.relative_to(home)): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in sorted(home.rglob("*"))
        if path.is_file()
    }


def _synthetic(column: sa.Column, table: str) -> Any:
    kind = column.type
    if isinstance(kind, sa.DateTime):
        return datetime(2026, 1, 2, 3, 4, 5, 678901)
    if isinstance(kind, sa.Boolean):
        return True
    if isinstance(kind, sa.Integer):
        return 7
    if isinstance(kind, sa.Float):
        return 0.1
    if isinstance(kind, sa.JSON):
        return {"nested": [1, "zwei", {"drei": None}], "ümlaut": 0.5}
    if isinstance(kind, sa.LargeBinary):
        return bytes(range(16))
    return f"{table}-{column.name}-é"


def fill_every_table(store: Store, home: Path) -> None:
    """Import a whole legacy home, then give every table the import left empty one row."""
    from immich_memories.store.legacy_imports import run_import

    run_import(store, home)
    with store.begin() as connection:
        for table in metadata.sorted_tables:
            if connection.execute(sa.select(sa.func.count()).select_from(table)).scalar():
                continue
            connection.execute(
                sa.insert(table), {c.name: _synthetic(c, table.name) for c in table.columns}
            )
