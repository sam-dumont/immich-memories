"""Legacy `annotations.sqlite` and `judgments.db` files, built the way the old code built them.

The DDL is the schema the app wrote before #871 moved these tables into the store; the rows
are synthetic.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

ANNOTATIONS_DDL = """
CREATE TABLE assets (asset_id TEXT PRIMARY KEY, taken_at TEXT, media_kind TEXT, favourite INTEGER,
 original_file TEXT, width INTEGER, height INTEGER, city TEXT, state TEXT, country TEXT,
 latitude REAL, longitude REAL, live_photo_video_id TEXT, duration_seconds REAL);
CREATE TABLE descriptions (
 asset_id TEXT, model TEXT, text TEXT, source TEXT, written_at TEXT, PRIMARY KEY(asset_id,model));
CREATE TABLE caption_provenance (
 asset_id TEXT, model TEXT, origin TEXT NOT NULL, PRIMARY KEY(asset_id,model));
CREATE TABLE description_fields (
 asset_id TEXT, model TEXT, field TEXT, value TEXT, written_at TEXT, PRIMARY KEY(asset_id,model,field));
CREATE TABLE asset_people (
 asset_id TEXT, person_name TEXT, person_id TEXT, birth_date TEXT, written_at TEXT,
 PRIMARY KEY(asset_id,person_name));
CREATE TABLE flags (
 asset_id TEXT, flag TEXT, evidence TEXT, source TEXT, written_at TEXT,
 PRIMARY KEY(asset_id,flag,source));
CREATE TABLE head_facts (
 asset_id TEXT, head TEXT, version TEXT, label TEXT, confidence REAL, encoder_key TEXT, decided_at TEXT,
 PRIMARY KEY(asset_id,head,version));
CREATE TABLE pixel_facts (
 asset_id TEXT PRIMARY KEY, producer_key TEXT, sharpness REAL, brightness REAL, contrast REAL,
 dark_fraction REAL, bright_fraction REAL, width INTEGER, height INTEGER, orientation TEXT,
 needs_rotation INTEGER, computed_at TEXT);
CREATE TABLE pixel_facts_thresholds (
 name TEXT PRIMARY KEY, value REAL, producer_key TEXT, n INTEGER, computed_at TEXT);
CREATE TABLE face_boxes (asset_id TEXT, named INTEGER, x1 REAL, y1 REAL, x2 REAL, y2 REAL);
CREATE TABLE face_reads (asset_id TEXT, producer TEXT, read_at TEXT, PRIMARY KEY(asset_id,producer));
CREATE TABLE motion_residuals (
 asset_id TEXT NOT NULL, producer TEXT NOT NULL, source_digest TEXT NOT NULL,
 measured TEXT NOT NULL, written_at TEXT NOT NULL, PRIMARY KEY(asset_id, producer));
CREATE TABLE motion_lines (
 asset_id TEXT NOT NULL, producer TEXT NOT NULL, source_digest TEXT NOT NULL,
 status TEXT NOT NULL, text TEXT NOT NULL, frames INTEGER NOT NULL, bytes_read INTEGER NOT NULL,
 written_at TEXT NOT NULL, PRIMARY KEY(asset_id, producer));
CREATE TABLE editorial_episode_readings (
 group_id TEXT NOT NULL, producer_key TEXT NOT NULL, evidence_key TEXT NOT NULL,
 full_asset_ids TEXT NOT NULL, what_happened TEXT NOT NULL, representatives TEXT NOT NULL,
 cull_decisions TEXT NOT NULL, answered_at TEXT NOT NULL DEFAULT (datetime('now')),
 PRIMARY KEY (group_id, producer_key, evidence_key));
CREATE TABLE library_overviews (node_key TEXT PRIMARY KEY, kind TEXT NOT NULL, period TEXT NOT NULL,
 account TEXT NOT NULL, children TEXT NOT NULL);
CREATE TABLE editorial_verdicts (asset_id TEXT NOT NULL, pass_version TEXT NOT NULL,
 bucket TEXT NOT NULL, decided_at TEXT NOT NULL DEFAULT (datetime('now')),
 PRIMARY KEY (asset_id, pass_version));
CREATE TABLE judgments (key TEXT PRIMARY KEY, answer TEXT NOT NULL,
 answered_at TEXT NOT NULL DEFAULT (datetime('now')));
"""

JUDGMENTS_DDL = """
CREATE TABLE judgments (key TEXT PRIMARY KEY, answer TEXT NOT NULL,
 answered_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE text_completion_failures (key TEXT PRIMARY KEY, record TEXT NOT NULL,
 recorded_at TEXT NOT NULL DEFAULT (datetime('now')));
"""

WRITTEN = "2026-03-01T09:30:00+00:00"


def write_annotations(path: Path) -> Path:
    """A small annotation file with one row in every table an old install had."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as legacy, legacy:
        legacy.executescript(ANNOTATIONS_DDL)
        legacy.executemany(
            "INSERT INTO assets (asset_id, taken_at, media_kind, favourite, live_photo_video_id)"
            " VALUES (?,?,?,?,?)",
            [
                ("still-1", "2025-06-01T10:00:00", "photo", 1, "clip-1"),
                ("clip-1", "2025-06-01T10:00:00", "video", 0, None),
            ],
        )
        legacy.execute(
            "INSERT INTO descriptions VALUES ('still-1','smolvlm','A picnic.','compact',?)",
            (WRITTEN,),
        )
        legacy.execute(
            "INSERT INTO description_fields VALUES ('still-1','smolvlm','setting','park',?)",
            (WRITTEN,),
        )
        legacy.execute(
            "INSERT INTO caption_provenance VALUES ('still-1','smolvlm','{\"model_id\": \"m\"}')"
        )
        legacy.execute(
            "INSERT INTO asset_people VALUES ('still-1','Person A','person-a',NULL,?)", (WRITTEN,)
        )
        legacy.executemany(
            "INSERT INTO flags VALUES (?,?,?,?,?)",
            [
                ("still-1", "cleared_family", '{"via": "web"}', "owner", WRITTEN),
                ("still-1", "nsfw", '{"reason": "detector"}', "a-detector", WRITTEN),
            ],
        )
        legacy.execute(
            "INSERT INTO head_facts VALUES ('still-1','nsfw_marqo','det-v3','no',0.02,'enc',?)",
            (WRITTEN,),
        )
        legacy.execute(
            "INSERT INTO pixel_facts VALUES ('still-1','pixel-facts-v1',120.5,110.0,40.0,0.01,"
            "0.02,1600,1200,'landscape',0,?)",
            (WRITTEN,),
        )
        legacy.execute(
            "INSERT INTO pixel_facts_thresholds VALUES ('sharpness_p10',35.0,'pixel-facts-v1',50,?)",
            (WRITTEN,),
        )
        legacy.executemany(
            "INSERT INTO face_boxes VALUES (?,?,?,?,?,?)",
            [("still-1", 1, 0.1, 0.1, 0.3, 0.4), ("still-1", 0, 0.5, 0.5, 0.6, 0.7)],
        )
        legacy.execute("INSERT INTO face_reads VALUES ('still-1','immich-faces-v1',?)", (WRITTEN,))
        legacy.execute(
            "INSERT INTO motion_residuals VALUES ('still-1','residual-v1','digest','{\"residual\": 2.5}',?)",
            (WRITTEN,),
        )
        legacy.execute(
            "INSERT INTO motion_lines VALUES ('clip-1','motion-v1','digest','described',"
            "'Someone waves.',3,1024,?)",
            (WRITTEN,),
        )
        legacy.execute(
            "INSERT INTO editorial_episode_readings (group_id, producer_key, evidence_key,"
            " full_asset_ids, what_happened, representatives, cull_decisions)"
            " VALUES ('group-1','producer-1','evidence-1','[\"still-1\"]','A picnic.',"
            '\'[{"asset_id":"still-1","reason":"the picnic"}]\',\'[]\')'
        )
        legacy.execute(
            "INSERT INTO library_overviews VALUES ('node-1','month','2025-06','June.','[]')"
        )
        legacy.execute(
            "INSERT INTO editorial_verdicts (asset_id, pass_version, bucket)"
            " VALUES ('still-1','cull-v1','kept')"
        )
        legacy.execute("INSERT INTO judgments (key, answer) VALUES ('question-a','answer-a')")
    return path


def write_judgments(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as legacy, legacy:
        legacy.executescript(JUDGMENTS_DDL)
        legacy.executemany(
            "INSERT INTO judgments (key, answer) VALUES (?, ?)",
            [("question-a", "answer-a"), ("question-b", "answer-b")],
        )
        legacy.execute(
            "INSERT INTO text_completion_failures (key, record) VALUES ('question-c', '{\"x\": 1}')"
        )
    return path
