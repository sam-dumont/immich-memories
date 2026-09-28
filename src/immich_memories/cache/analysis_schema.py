"""The analysis cache's tables, stamped with one version instead of migrated.

`cache.db` holds only what can be computed again: video analysis and its segments, the hash
index, video metadata and the look-failure ledger. So it is never migrated. `PRAGMA
user_version` records the layout it was built with; any other layout has its cache tables
dropped and rebuilt empty.

The layout below is exactly what the old migration ladder left at its last step (v25), so a
cache that ladder finished is adopted as it stands and keeps its analysis. The store's old
tables that may still sit in an old `cache.db` (runs, attempts, scores, ...) are never
touched here: the legacy import reads them.
"""

from __future__ import annotations

import logging
import sqlite3

logger = logging.getLogger(__name__)

CACHE_VERSION = 1
# The migration ladder's last step, whose layout CACHE_VERSION 1 is.
_LADDER_FINAL = 25

_TABLES = (
    "video_segments",
    "hash_index",
    "video_analysis",
    "video_metadata",
    "asset_look_failures",
)

_DDL = """
CREATE TABLE video_analysis (
    asset_id TEXT PRIMARY KEY,
    checksum TEXT,
    file_modified_at TEXT,
    analysis_timestamp TEXT NOT NULL,
    analysis_version INTEGER NOT NULL DEFAULT 1,
    perceptual_hash TEXT,
    thumbnail_hash TEXT,
    duration_seconds REAL,
    width INTEGER,
    height INTEGER,
    bitrate INTEGER,
    fps REAL,
    codec TEXT,
    color_space TEXT,
    color_transfer TEXT,
    color_primaries TEXT,
    bit_depth INTEGER,
    best_face_score REAL,
    best_motion_score REAL,
    best_stability_score REAL,
    best_audio_score REAL,
    best_total_score REAL,
    motion_summary TEXT,
    audio_levels TEXT,
    file_created_at TEXT,
    scoring_version INTEGER NOT NULL DEFAULT 1,
    model_version TEXT
);
CREATE INDEX idx_video_analysis_hash ON video_analysis(perceptual_hash);
CREATE INDEX idx_video_analysis_created ON video_analysis(file_created_at);
CREATE INDEX idx_video_analysis_checksum ON video_analysis(checksum);

CREATE TABLE video_segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id TEXT NOT NULL,
    segment_index INTEGER NOT NULL,
    start_time REAL NOT NULL,
    end_time REAL NOT NULL,
    start_frame INTEGER,
    end_frame INTEGER,
    face_score REAL,
    motion_score REAL,
    stability_score REAL,
    audio_score REAL,
    total_score REAL,
    face_positions TEXT,
    motion_vectors TEXT,
    keyframe_path TEXT,
    llm_description TEXT,
    llm_emotion TEXT,
    llm_setting TEXT,
    llm_activities TEXT,
    llm_subjects TEXT,
    llm_interestingness REAL,
    llm_quality REAL,
    audio_categories TEXT,
    transcript TEXT,
    transcript_language TEXT,
    transcript_confidence REAL,
    llm_category TEXT,
    safe_cut_gaps TEXT,
    FOREIGN KEY (asset_id) REFERENCES video_analysis(asset_id) ON DELETE CASCADE,
    UNIQUE(asset_id, segment_index)
);
CREATE INDEX idx_segments_asset ON video_segments(asset_id);
CREATE INDEX idx_segments_score ON video_segments(total_score DESC);

CREATE TABLE hash_index (
    asset_id TEXT PRIMARY KEY,
    hash_chunk_0 TEXT,
    hash_chunk_1 TEXT,
    hash_chunk_2 TEXT,
    hash_chunk_3 TEXT,
    full_hash TEXT NOT NULL,
    FOREIGN KEY (asset_id) REFERENCES video_analysis(asset_id) ON DELETE CASCADE
);
CREATE INDEX idx_hash_chunk_0 ON hash_index(hash_chunk_0);
CREATE INDEX idx_hash_chunk_1 ON hash_index(hash_chunk_1);
CREATE INDEX idx_hash_chunk_2 ON hash_index(hash_chunk_2);
CREATE INDEX idx_hash_chunk_3 ON hash_index(hash_chunk_3);

CREATE TABLE video_metadata (
    asset_id TEXT PRIMARY KEY,
    checksum TEXT,
    duration_seconds REAL,
    width INTEGER,
    height INTEGER,
    bitrate INTEGER,
    fps REAL,
    codec TEXT,
    color_space TEXT,
    color_transfer TEXT,
    color_primaries TEXT,
    bit_depth INTEGER,
    cached_at TEXT NOT NULL DEFAULT (datetime('now')),
    rotation INTEGER DEFAULT 0
);
CREATE INDEX idx_video_metadata_checksum ON video_metadata(checksum);

CREATE TABLE asset_look_failures (
    asset_id TEXT NOT NULL,
    model_version TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 1,
    last_attempt_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (asset_id, model_version)
);
"""


def ensure_cache_schema(conn: sqlite3.Connection) -> None:
    """Build the cache tables, adopt a finished ladder's, or rebuild any other layout.

    Runs under `BEGIN IMMEDIATE`, so two processes opening the cache together build it once.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        stamp = conn.execute("PRAGMA user_version").fetchone()[0]
        if stamp != CACHE_VERSION:
            present = {
                name
                for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            finished = stamp == 0 and _ladder_version(conn) == _LADDER_FINAL
            if not (finished and present.issuperset(_TABLES)):
                _rebuild(conn, stamp, present)
            conn.execute(f"PRAGMA user_version = {CACHE_VERSION}")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _ladder_version(conn: sqlite3.Connection) -> int | None:
    try:
        return conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
    except sqlite3.OperationalError:
        return None


def _rebuild(conn: sqlite3.Connection, stamp: int, present: set[str]) -> None:
    stale = [name for name in _TABLES if name in present]
    if stale:
        logger.info("Rebuilding the analysis cache (layout %s, now %s)", stamp, CACHE_VERSION)
    for name in stale:
        conn.execute(f"DROP TABLE {name}")  # nosemgrep: sqlalchemy-execute-raw-query — fixed names
    for statement in _DDL.split(";"):
        if statement.strip():
            conn.execute(statement)
