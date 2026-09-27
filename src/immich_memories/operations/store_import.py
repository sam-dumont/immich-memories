"""The one-time import of operations history from the files it used to live in (#871).

Reads, never writes: `cache.db`'s run history, phase timings, automation attempts,
notification health and banked asset scores; the run index JSON under
`<cache>/editorial-runs/by-run/`; and `special-days.json`. A row the store already holds
is never replaced by a legacy one, so running this twice imports nothing the second time.
Run ids, attempt ids and memory keys are carried exactly; ISO text timestamps become the
store's naive UTC (see `_when` for the few written without an offset).
"""

from __future__ import annotations

import json
import operator
import sqlite3
from collections.abc import Callable, Iterable, Sequence
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from immich_memories.db import Store, now_db, to_db
from immich_memories.db.legacy_import import ImportOutcome
from immich_memories.db.tables import (
    asset_scores,
    automation_attempts,
    notification_health,
    phase_stats,
    pipeline_runs,
    run_attempts,
    special_days,
)

_DEFAULT_CACHE_DB = "~/.immich-memories/cache.db"
_DEFAULT_CACHE_DIR = "~/.immich-memories/cache"
_CHUNK = 900

Row = dict[str, Any]


class _Tally:
    def __init__(self) -> None:
        self.imported = 0
        self.skipped = 0
        self.notes: list[str] = []

    def outcome(self, source: str) -> ImportOutcome:
        return ImportOutcome(source, self.imported, self.skipped, tuple(self.notes))


def import_legacy(store: Store, home: Path) -> ImportOutcome:
    """Bring run history, automation state, asset scores, the run index and special days in.

    `home` is the `~/.immich-memories` directory. `cache.db` and the cache directory are
    found where the loaded config puts them when it moved them, beside `home` otherwise.
    """
    cache_db, cache_dir = _legacy_locations(home)
    catalogue = home / "special-days.json"
    tally = _Tally()
    _import_cache_db(store, cache_db, tally)
    _import_run_index(store, cache_dir / "editorial-runs" / "by-run", tally)
    _import_special_days(store, catalogue, tally)
    return tally.outcome(f"{cache_db}, {cache_dir}, {catalogue}")


def _legacy_locations(home: Path) -> tuple[Path, Path]:
    from immich_memories.config_loader import get_config

    cache = get_config().cache
    cache_db = home / "cache.db" if cache.database == _DEFAULT_CACHE_DB else cache.database_path
    cache_dir = home / "cache" if cache.directory == _DEFAULT_CACHE_DIR else cache.cache_path
    return cache_db, cache_dir


# --- cache.db -------------------------------------------------------------------------------


def _import_cache_db(store: Store, path: Path, tally: _Tally) -> None:
    if not path.is_file():
        tally.notes.append(f"no {path.name}")
        return
    try:
        legacy = _read_cache_db(path)
    except sqlite3.Error as exc:
        tally.notes.append(f"{path.name} not readable: {exc}")
        return
    runs = [_run(r) for r in legacy["pipeline_runs"]]
    if _schema_version(legacy) < 11:
        runs = [_v11_identity(run) for run in runs]
    with store.begin() as conn:
        new_runs = _insert_new(conn, pipeline_runs, ["run_id"], runs, tally)
        # Phase timings have no key of their own: they come in with a run new to the store.
        phases = [_phase(r) for r in legacy["phase_stats"] if r.get("run_id") in new_runs]
        if phases:
            conn.execute(sa.insert(phase_stats), phases)
        tally.imported += len(phases)
        tally.skipped += len(legacy["phase_stats"]) - len(phases)
        _import_attempts(conn, legacy["automation_attempts"], tally)
        health = [_health(r) for r in legacy["notification_health"] if r.get("id") == 1]
        _insert_new(conn, notification_health, ["id"], health, tally)
        _insert_new(
            conn,
            asset_scores,
            ["asset_id", "model_version"],
            _dedup_scores([_score(r) for r in legacy["asset_scores"]]),
            tally,
        )


def _read_cache_db(path: Path) -> dict[str, list[Row]]:
    uri = f"{path.resolve().as_uri()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=30.0)) as conn:
        conn.row_factory = sqlite3.Row
        present = {
            name for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        order = {
            "phase_stats": "id",
            "automation_attempts": "rowid",
            "schema_migrations": "version",
        }
        tables = (
            "schema_migrations",
            "pipeline_runs",
            "phase_stats",
            "automation_attempts",
            "notification_health",
            "asset_scores",
        )
        return {
            table: (
                [
                    dict(row)
                    for row in conn.execute(
                        f"SELECT * FROM {table} ORDER BY {order.get(table, 'rowid')}"  # noqa: S608  # nosemgrep: sqlalchemy-execute-raw-query — table and order are fixed names above
                    )
                ]
                if table in present
                else []
            )
            for table in tables
        }


def _schema_version(legacy: dict[str, list[Row]]) -> int:
    versions = [row["version"] for row in legacy["schema_migrations"] if "version" in row]
    return max(versions, default=0)


# What cache schema v11 back-filled on a completed auto run that predates the category.
_CATEGORY_OF_TYPE = {
    "year_in_review": "year_in_review",
    "trip": "trip",
    "multi_person": "multi_person",
    "on_this_day": "on_this_day",
    "person_spotlight": "person_spotlight",
    "monthly_highlights": "monthly_review",
}


def _v11_identity(run: Row) -> Row:
    """The conservative identity v11 gave a pre-v11 completed auto run, so dedup agrees."""
    if run["status"] != "completed" or run["source"] != "auto":
        return run
    if run["memory_category"] is None:
        run["memory_category"] = _CATEGORY_OF_TYPE.get(run["memory_type"] or "")
    person = " ".join((run["person_name"] or "").split()).casefold()
    if not run["memory_people"] and person:
        run["memory_people"] = [person]
    return run


def _insert_new(
    conn: Connection, table: sa.Table, keys: Sequence[str], rows: list[Row], tally: _Tally
) -> set[Any]:
    """Insert the rows whose key the store does not hold yet; return the keys inserted."""
    key_of: Callable[[Row], Any] = (
        operator.itemgetter(keys[0])
        if len(keys) == 1
        else (lambda row: tuple(row[k] for k in keys))
    )
    held = _held_keys(conn, table, keys, [key_of(row) for row in rows])
    fresh: dict[Any, Row] = {}
    for row in rows:
        key = key_of(row)
        if key in held or key in fresh:
            tally.skipped += 1
        else:
            fresh[key] = row
    if fresh:
        conn.execute(sa.insert(table), list(fresh.values()))
        tally.imported += len(fresh)
    return set(fresh)


def _held_keys(conn: Connection, table: sa.Table, keys: Sequence[str], wanted: list[Any]) -> set:
    if not wanted:
        return set()
    if len(keys) == 1:
        column = table.c[keys[0]]
        held: set[Any] = set()
        for start in range(0, len(wanted), _CHUNK):
            chunk = wanted[start : start + _CHUNK]
            held.update(conn.execute(sa.select(column).where(column.in_(chunk))).scalars())
        return held
    # Composite keys (asset scores): chunk on the first column, match the rest here.
    first = table.c[keys[0]]
    firsts = sorted({key[0] for key in wanted})
    held = set()
    for start in range(0, len(firsts), _CHUNK):
        chunk = firsts[start : start + _CHUNK]
        query = sa.select(*(table.c[k] for k in keys)).where(first.in_(chunk))
        held.update(conn.execute(query))
    return held


def _import_attempts(conn: Connection, legacy: list[Row], tally: _Tally) -> None:
    """Legacy attempts in rowid order, one INSERT each, so the database numbers them in that
    order and its own counter stays in step (no explicit `seq` is ever written)."""
    rows = [_attempt(row) for row in legacy]
    held = _held_keys(conn, automation_attempts, ["id"], [row["id"] for row in rows])
    for row in rows:
        if row["id"] in held:
            tally.skipped += 1
            continue
        conn.execute(sa.insert(automation_attempts), row)
        held.add(row["id"])
        tally.imported += 1


def _dedup_scores(rows: list[Row]) -> list[Row]:
    """Pre-v22 caches may hold an asset twice once NULL versions fold onto `''`: newest wins."""
    newest: dict[tuple[str, str], Row] = {}
    for row in rows:
        newest[(row["asset_id"], row["model_version"])] = row
    return list(newest.values())


def _json(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except ValueError:
        return default


def _when(value: Any, *, naive_is_local: bool = True) -> datetime | None:
    """A legacy timestamp as naive UTC.

    Run, phase and attempt times without an offset predate cache schema v11 and are the
    machine's local wall time, exactly as v11 read them; SQLite's `datetime('now')` (the
    asset scores) is UTC.
    """
    if not value:
        return None
    try:
        instant = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if instant.tzinfo is None and naive_is_local:
        instant = instant.astimezone(UTC)
    return to_db(instant)


def _run(row: Row) -> Row:
    minutes = row.get("target_duration_minutes")
    target = row.get("target_duration_seconds")
    if target is None:
        target = (minutes or 10) * 60
    return {
        "run_id": row["run_id"],
        "created_at": _when(row.get("created_at")) or now_db(),
        "completed_at": _when(row.get("completed_at")),
        "status": row.get("status") or "running",
        "memory_type": row.get("memory_type"),
        "memory_key": row.get("memory_key"),
        "memory_category": row.get("memory_category"),
        "memory_people": _json(row.get("memory_people_json"), []),
        "source": row.get("source") or "manual",
        "automation_attempt_id": row.get("automation_attempt_id"),
        "last_phase": row.get("last_phase"),
        "phase_events": _json(row.get("phase_events"), []),
        "person_name": row.get("person_name"),
        "person_id": row.get("person_id"),
        "date_range_start": row.get("date_range_start"),
        "date_range_end": row.get("date_range_end"),
        "target_duration_seconds": target,
        "output_path": row.get("output_path"),
        "output_size_bytes": row.get("output_size_bytes") or 0,
        "output_duration_seconds": row.get("output_duration_seconds") or 0.0,
        "clips_analyzed": row.get("clips_analyzed") or 0,
        "clips_selected": row.get("clips_selected") or 0,
        "errors_count": row.get("errors_count") or 0,
        "system_info": _json(row.get("system_info"), None),
        "delivery_status": row.get("delivery_status") or "not_requested",
        "delivery_attempts": row.get("delivery_attempts") or 0,
        "delivery_error": row.get("delivery_error"),
        "immich_asset_id": row.get("immich_asset_id"),
        "delivery_album": row.get("delivery_album"),
        "warnings": _json(row.get("warnings_json"), []),
        "llm_metrics": _json(row.get("llm_metrics"), None) or None,
        "title_source": row.get("title_source"),
    }


def _phase(row: Row) -> Row:
    return {
        "run_id": row["run_id"],
        "phase_name": row.get("phase_name") or "",
        "started_at": _when(row.get("started_at")) or now_db(),
        "completed_at": _when(row.get("completed_at")),
        "duration_seconds": row.get("duration_seconds") or 0.0,
        "items_processed": row.get("items_processed") or 0,
        "items_total": row.get("items_total") or 0,
        "errors": _json(row.get("errors"), None),
        "extra_metrics": _json(row.get("extra_metrics"), None),
    }


def _attempt(row: Row) -> Row:
    return {
        "id": row["id"],
        "started_at": _when(row.get("started_at")) or now_db(),
        "finished_at": _when(row.get("finished_at")),
        "outcome": row.get("outcome") or "failed",
        "reason": row.get("reason") or "",
        "candidate_category": row.get("candidate_category"),
        "memory_type": row.get("memory_type"),
        "memory_key": row.get("memory_key"),
        "run_id": row.get("run_id"),
        "error": row.get("error"),
        "last_phase": row.get("last_phase"),
        "phase_events": _json(row.get("phase_events"), []),
    }


def _health(row: Row) -> Row:
    return {
        "id": 1,
        "last_attempt_at": _when(row.get("last_attempt_at")),
        "last_success_at": _when(row.get("last_success_at")),
        "last_failure_at": _when(row.get("last_failure_at")),
        "failure_category": row.get("failure_category"),
        "failure_message": row.get("failure_message"),
    }


def _score(row: Row) -> Row:
    return {
        "asset_id": row["asset_id"],
        "model_version": row.get("model_version") or "",
        "asset_type": row.get("asset_type") or "unknown",
        "llm_interest": row.get("llm_interest"),
        "llm_quality": row.get("llm_quality"),
        "llm_emotion": row.get("llm_emotion"),
        "llm_description": row.get("llm_description"),
        "llm_category": row.get("llm_category"),
        "metadata_score": row.get("metadata_score") or 0.0,
        "combined_score": row.get("combined_score") or 0.0,
        "analyzed_at": _when(row.get("analyzed_at"), naive_is_local=False) or now_db(),
    }


# --- the run index and special days ---------------------------------------------------------


def _index_records(directory: Path, tally: _Tally) -> Iterable[Row]:
    for path in sorted(directory.glob("*.json")):
        try:
            record = json.loads(path.read_text())
            attempt_dir = str(record["attempt_dir"])
        except (OSError, ValueError, KeyError, TypeError):
            tally.skipped += 1
            tally.notes.append(f"run index {path.name} not readable")
            continue
        yield {
            "run_id": str(record.get("run_id") or path.stem),
            "attempt_dir": attempt_dir,
            "output_path": str(record.get("output_path") or ""),
            "recorded_at": datetime.fromtimestamp(path.stat().st_mtime, UTC).replace(tzinfo=None),
        }


def _import_run_index(store: Store, directory: Path, tally: _Tally) -> None:
    if not directory.is_dir():
        tally.notes.append("no run index")
        return
    rows = list(_index_records(directory, tally))
    with store.begin() as conn:
        _insert_new(conn, run_attempts, ["run_id"], rows, tally)


def _import_special_days(store: Store, path: Path, tally: _Tally) -> None:
    """The catalogue is one ordered document: it comes in whole, into an empty catalogue only."""
    if not path.is_file():
        tally.notes.append(f"no {path.name}")
        return
    try:
        records = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        tally.notes.append(f"{path.name} not readable: {exc}")
        return
    if not isinstance(records, list):
        tally.notes.append(f"{path.name} is not a list")
        return
    with store.begin() as conn:
        if conn.execute(sa.select(sa.func.count()).select_from(special_days)).scalar():
            tally.skipped += len(records)
            tally.notes.append("the store already holds a special-days catalogue")
            return
        if records:
            conn.execute(
                sa.insert(special_days),
                [{"position": index, "record": record} for index, record in enumerate(records)],
            )
        tally.imported += len(records)
