"""Bring `annotations.sqlite` and `judgments.db` into the store, once, without touching them.

Every row keeps its primary key: those are the content keys a replay finds an answer by. A
key the store already holds keeps the store's row, so a newer answer is never replaced by an
older one from a file. The files are opened read-only and never written, and a second run
imports nothing.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import closing
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy import Boolean, DateTime, Float, Integer, Table

from immich_memories.analysis.editorial_shareability import OWNER_SOURCE
from immich_memories.db import Store, now_db, to_db
from immich_memories.db.legacy_import import ImportOutcome
from immich_memories.db.tables import (
    annotation_assets,
    asset_flags,
    asset_people,
    caption_provenance,
    description_fields,
    description_unavailable,
    descriptions,
    editorial_episode_readings,
    editorial_episode_refusals,
    editorial_verdicts,
    face_boxes,
    face_reads,
    head_facts,
    judgments,
    library_overviews,
    live_clock_offsets,
    motion_bursts,
    motion_lines,
    motion_residuals,
    pixel_facts,
    pixel_facts_thresholds,
    speech_regions,
    text_completion_failures,
)
from immich_memories.store.batches import id_in, in_chunks, upsert_rows

logger = logging.getLogger(__name__)

# The file's table name, and the store table its rows go to.
_ANNOTATION_TABLES: tuple[tuple[str, Table], ...] = (
    ("assets", annotation_assets),
    ("descriptions", descriptions),
    ("description_fields", description_fields),
    ("caption_provenance", caption_provenance),
    ("description_unavailable", description_unavailable),
    ("asset_people", asset_people),
    ("flags", asset_flags),
    ("head_facts", head_facts),
    ("pixel_facts", pixel_facts),
    ("pixel_facts_thresholds", pixel_facts_thresholds),
    ("face_reads", face_reads),
    ("motion_bursts", motion_bursts),
    ("motion_residuals", motion_residuals),
    ("speech_regions", speech_regions),
    ("live_clock_offsets", live_clock_offsets),
    ("motion_lines", motion_lines),
    ("editorial_episode_readings", editorial_episode_readings),
    ("editorial_episode_refusals", editorial_episode_refusals),
    ("library_overviews", library_overviews),
    ("editorial_verdicts", editorial_verdicts),
    ("judgments", judgments),
    ("text_completion_failures", text_completion_failures),
)
_JUDGMENT_TABLES = (
    ("judgments", judgments),
    ("text_completion_failures", text_completion_failures),
)
# A column the file never had reads as the value the old code gave it.
_DEFAULTS = {"notable_moments": "[]"}
_BATCH = 1000


def legacy_files(home: Path) -> tuple[list[Path], list[Path]]:
    """The annotation files and judgment files the current code would have used under `home`."""
    caches = [home / "cache"]
    annotations = [home / "cache" / "annotations.sqlite"]
    config_path = home / "config.yaml"
    if config_path.is_file():
        try:
            from immich_memories.config_loader import Config

            config = Config.from_yaml(config_path)
            caches.append(config.cache.cache_path)
            annotations.append(
                config.editorial.resolve_annotation_database(config.cache.cache_path)
            )
        except Exception as exc:  # WHY: a config that no longer loads still has default files
            logger.warning("config.yaml unreadable for the import (%s): default paths only", exc)
    judgment_files = [cache / "judgments.db" for cache in caches]
    return _existing(annotations), _existing(judgment_files)


def _existing(paths: Sequence[Path]) -> list[Path]:
    seen: dict[Path, Path] = {}
    for path in paths:
        if path.is_file():
            seen.setdefault(path.resolve(), path)
    return list(seen.values())


def import_legacy(store: Store, home: Path) -> ImportOutcome:
    """Copy every legacy annotation and judgment row the store does not hold yet.

    `home` is the `~/.immich-memories` directory; `editorial.annotation_database` in its
    config.yaml names a relocated annotation file. `text-judgments.sqlite` files beside
    research attempts are not searched for.
    """
    annotations, judgment_files = legacy_files(home)
    sources = [(path, _ANNOTATION_TABLES) for path in annotations] + [
        (path, _JUDGMENT_TABLES) for path in judgment_files
    ]
    if not sources:
        return ImportOutcome(str(home), 0, 0, ("no annotations.sqlite or judgments.db",))
    imported = skipped = 0
    notes: list[str] = []
    for path, tables in sources:
        try:
            counts = _import_file(store, path, tables)
        except sqlite3.Error as exc:
            notes.append(f"{path}: not readable ({exc})")
            continue
        for table, (taken, left) in counts.items():
            imported += taken
            skipped += left
            notes.append(f"{path.name}:{table}: {taken} imported, {left} already in the store")
    return ImportOutcome(
        ", ".join(str(path) for path, _ in sources), imported, skipped, tuple(notes)
    )


def _read_only(path: Path) -> sqlite3.Connection:
    uri = path.resolve().as_uri()
    try:
        connection = sqlite3.connect(f"{uri}?mode=ro", uri=True)
        connection.execute("SELECT 1 FROM sqlite_master").fetchone()
        return connection
    except sqlite3.OperationalError:
        # A WAL file with no -shm beside it, in a directory we may not write, opens only as an
        # immutable snapshot. Nothing writes the file after the cutover, so that is safe.
        return sqlite3.connect(f"{uri}?mode=ro&immutable=1", uri=True)


def _import_file(
    store: Store, path: Path, tables: Sequence[tuple[str, Table]]
) -> dict[str, tuple[int, int]]:
    counts: dict[str, tuple[int, int]] = {}
    with closing(_read_only(path)) as legacy:
        present = {
            str(row[0])
            for row in legacy.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        for name, table in tables:
            if name in present:
                counts[table.name] = _copy_table(store, legacy, name, table)
        if "face_boxes" in present:
            counts[face_boxes.name] = _copy_face_boxes(store, legacy)
    return counts


def _copy_table(
    store: Store, legacy: sqlite3.Connection, name: str, table: Table
) -> tuple[int, int]:
    have = _legacy_columns(legacy, name)
    wanted = [column for column in table.columns if column.name in have]
    keys = [column.name for column in table.primary_key.columns]
    if not set(keys) <= have:
        return 0, 0
    before = _count(store, table)
    offered = 0
    for batch in _batches(legacy, name, [column.name for column in wanted]):
        rows = [_converted(table, row) for row in batch]
        offered += len(rows)
        if table is asset_flags:
            rows = _without_decided(store, rows)
        with store.begin() as connection:
            upsert_rows(connection, table, _unique(rows, keys), keys=keys, update=())
    taken = _count(store, table) - before
    return taken, offered - taken


def _copy_face_boxes(store: Store, legacy: sqlite3.Connection) -> tuple[int, int]:
    """Boxes had no key in the file: number each picture's boxes in the order they were read.

    A picture the store already holds boxes for keeps the store's read whole.
    """
    have = _legacy_columns(legacy, "face_boxes")
    columns = [c for c in ("asset_id", "named", "x1", "y1", "x2", "y2", "person_id") if c in have]
    boxes: dict[str, list[dict[str, Any]]] = {}
    for batch in _batches(legacy, "face_boxes", columns, order="rowid"):
        for row in batch:
            converted = _converted(face_boxes, row)
            asset_id = converted["asset_id"]
            converted["ordinal"] = len(boxes.setdefault(asset_id, []))
            boxes[asset_id].append(converted)
    held = _assets_with_boxes(store, list(boxes))
    rows = [row for asset_id, rows in boxes.items() if asset_id not in held for row in rows]
    skipped = sum(len(rows) for asset_id, rows in boxes.items() if asset_id in held)
    for start in range(0, len(rows), _BATCH):
        with store.begin() as connection:
            upsert_rows(
                connection,
                face_boxes,
                rows[start : start + _BATCH],
                keys=("asset_id", "ordinal"),
                update=(),
            )
    return len(rows), skipped


def _without_decided(store: Store, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A picture carries one owner decision: one the store holds keeps it over the file's."""
    owners = [row["asset_id"] for row in rows if row["source"] == OWNER_SOURCE]
    decided: set[str] = set()
    with store.connect() as connection:
        for chunk in in_chunks(connection, owners):
            found: list[Any] = list(
                connection.execute(
                    sa.select(asset_flags.c.asset_id).where(
                        asset_flags.c.source == OWNER_SOURCE,
                        id_in(connection, asset_flags.c.asset_id, chunk),
                    )
                ).scalars()
            )
            decided.update(str(asset_id) for asset_id in found)
    return [row for row in rows if row["source"] != OWNER_SOURCE or row["asset_id"] not in decided]


def _assets_with_boxes(store: Store, asset_ids: list[str]) -> set[str]:
    held: set[str] = set()
    with store.connect() as connection:
        for chunk in in_chunks(connection, asset_ids):
            found: list[Any] = list(
                connection.execute(
                    sa.select(face_boxes.c.asset_id).where(
                        id_in(connection, face_boxes.c.asset_id, chunk)
                    )
                ).scalars()
            )
            held.update(str(asset_id) for asset_id in found)
    return held


def _legacy_columns(legacy: sqlite3.Connection, name: str) -> set[str]:
    return {str(row[1]) for row in legacy.execute(f"PRAGMA table_info({name})")}  # noqa: S608


def _batches(
    legacy: sqlite3.Connection, name: str, columns: Sequence[str], order: str = ""
) -> Iterator[list[dict[str, Any]]]:
    # Names come from our own table list and the file's own PRAGMA, never from a user.
    query = f"SELECT {', '.join(columns)} FROM {name}"  # noqa: S608
    cursor = legacy.execute(query + (f" ORDER BY {order}" if order else ""))
    while rows := cursor.fetchmany(_BATCH):
        yield [dict(zip(columns, row, strict=True)) for row in rows]


def _converted(table: Table, row: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for column in table.columns:
        if column.name not in row:
            if not column.primary_key:
                out[column.name] = _DEFAULTS.get(column.name)
            continue
        out[column.name] = _value(column.type, row[column.name])
        if out[column.name] is None and not column.nullable and isinstance(column.type, DateTime):
            out[column.name] = now_db()
    return out


def _value(kind: Any, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(kind, DateTime):
        try:
            return to_db(str(value))
        except ValueError:
            return None
    if isinstance(kind, Boolean):
        return bool(value)
    if isinstance(kind, Integer):
        return _number(int, value)
    if isinstance(kind, Float):
        return _number(float, value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value if isinstance(value, str) else str(value)


def _number(kind: type, value: Any) -> Any:
    try:
        return kind(value)
    except (TypeError, ValueError):
        return None


def _unique(rows: list[dict[str, Any]], keys: Sequence[str]) -> list[dict[str, Any]]:
    # SQLite lets a key column hold NULL, which no store key can: such a row is left behind.
    # A key twice in one batch keeps its first row, as a do-nothing insert would.
    seen: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        key = tuple(row[name] for name in keys)
        if None not in key:
            seen.setdefault(key, row)
    return list(seen.values())


def _count(store: Store, table: Table) -> int:
    with store.connect() as connection:
        return int(connection.execute(sa.select(sa.func.count()).select_from(table)).scalar() or 0)
