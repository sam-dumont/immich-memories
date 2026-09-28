"""What the app learned about each picture, formerly `annotations.sqlite`.

Source metadata, captions, head and detector answers, pixel and face facts, the facts a cut
measures, and the owner's own decisions (`asset_flags` rows with `source='owner'`). Primary
keys are the ones the file had: they are the content keys a replay finds an answer by.
Every answer keeps its producer and when it was written.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, Table, Text

from immich_memories.db.metadata import metadata

annotation_assets = Table(
    "annotation_assets",
    metadata,
    Column("asset_id", Text, primary_key=True),
    Column("taken_at", DateTime),
    Column("media_kind", Text),
    Column("favourite", Boolean),
    Column("original_file", Text),
    Column("width", Integer),
    Column("height", Integer),
    Column("city", Text),
    Column("state", Text),
    Column("country", Text),
    Column("latitude", Float),
    Column("longitude", Float),
    Column("live_photo_video_id", Text),
    Column("duration_seconds", Float),
)

descriptions = Table(
    "descriptions",
    metadata,
    Column("asset_id", Text, primary_key=True),
    Column("model", Text, primary_key=True),
    Column("text", Text),
    Column("source", Text),
    Column("written_at", DateTime),
)

description_fields = Table(
    "description_fields",
    metadata,
    Column("asset_id", Text, primary_key=True),
    Column("model", Text, primary_key=True),
    Column("field", Text, primary_key=True),
    Column("value", Text),
    Column("written_at", DateTime),
)

caption_provenance = Table(
    "caption_provenance",
    metadata,
    Column("asset_id", Text, primary_key=True),
    Column("model", Text, primary_key=True),
    Column("origin", Text, nullable=False),
)

description_unavailable = Table(
    "description_unavailable",
    metadata,
    Column("asset_id", Text, primary_key=True),
    Column("model", Text, primary_key=True),
    Column("source", Text, nullable=False),
    Column("version", Text, nullable=False),
    Column("producer_key", Text, nullable=False),
    Column("preview_sha256", Text, nullable=False),
    Column("image_sha256", Text, nullable=False),
    Column("request_sha256", Text, nullable=False),
    Column("request_json", Text, nullable=False),
    Column("attempts_json", Text, nullable=False),
    Column("written_at", DateTime, nullable=False),
)

asset_people = Table(
    "asset_people",
    metadata,
    Column("asset_id", Text, primary_key=True),
    Column("person_name", Text, primary_key=True),
    Column("person_id", Text),
    Column("birth_date", Text),
    Column("written_at", DateTime),
)

# `source='owner'` rows are the owner's own decisions (store/owner_decisions.py); every other
# source is a producer's warning.
asset_flags = Table(
    "asset_flags",
    metadata,
    Column("asset_id", Text, primary_key=True),
    Column("flag", Text, primary_key=True),
    Column("source", Text, primary_key=True),
    Column("evidence", Text),
    Column("written_at", DateTime),
)

head_facts = Table(
    "head_facts",
    metadata,
    Column("asset_id", Text, primary_key=True),
    Column("head", Text, primary_key=True),
    Column("version", Text, primary_key=True),
    Column("label", Text),
    Column("confidence", Float),
    Column("encoder_key", Text),
    Column("decided_at", DateTime),
)

pixel_facts = Table(
    "pixel_facts",
    metadata,
    Column("asset_id", Text, primary_key=True),
    Column("producer_key", Text),
    Column("sharpness", Float),
    Column("brightness", Float),
    Column("contrast", Float),
    Column("dark_fraction", Float),
    Column("bright_fraction", Float),
    Column("width", Integer),
    Column("height", Integer),
    Column("orientation", Text),
    Column("needs_rotation", Boolean),
    Column("computed_at", DateTime),
)

pixel_facts_thresholds = Table(
    "pixel_facts_thresholds",
    metadata,
    Column("name", Text, primary_key=True),
    Column("value", Float),
    Column("producer_key", Text),
    Column("n", Integer),
    Column("computed_at", DateTime),
)

# The file kept boxes without a key; `ordinal` is the box's place in its picture's read.
face_boxes = Table(
    "face_boxes",
    metadata,
    Column("asset_id", Text, primary_key=True),
    Column("ordinal", Integer, primary_key=True, autoincrement=False),
    Column("named", Boolean),
    Column("x1", Float),
    Column("y1", Float),
    Column("x2", Float),
    Column("y2", Float),
    Column("person_id", Text),
)

face_reads = Table(
    "face_reads",
    metadata,
    Column("asset_id", Text, primary_key=True),
    Column("producer", Text, primary_key=True),
    Column("read_at", DateTime),
)

motion_bursts = Table(
    "motion_bursts",
    metadata,
    Column("asset_id", Text, primary_key=True),
    Column("burst_id", Text),
    Column("still_ids", Text),
    Column("video_ids", Text),
    Column("duration_seconds", Float),
    Column("beats_a_still", Boolean),
    Column("minimum_seconds", Float),
    Column("computed_at", DateTime),
)


def _measurement(name: str) -> Table:
    return Table(
        name,
        metadata,
        Column("asset_id", Text, primary_key=True),
        Column("producer", Text, primary_key=True),
        Column("source_digest", Text, nullable=False),
        Column("measured", Text, nullable=False),
        Column("written_at", DateTime, nullable=False),
    )


motion_residuals = _measurement("motion_residuals")
speech_regions = _measurement("speech_regions")
live_clock_offsets = _measurement("live_clock_offsets")

motion_lines = Table(
    "motion_lines",
    metadata,
    Column("asset_id", Text, primary_key=True),
    Column("producer", Text, primary_key=True),
    Column("source_digest", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("text", Text, nullable=False),
    Column("frames", Integer, nullable=False),
    Column("bytes_read", Integer, nullable=False),
    Column("written_at", DateTime, nullable=False),
    Column("provenance", Text),
)
