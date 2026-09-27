"""Every store table, registered on the shared `metadata` by importing its module here.

A new domain adds `db/tables/<domain>.py`, imports it below, and ships an Alembic revision
creating what it declares; `tests/store/test_migrations.py` fails until the two agree.
"""

from immich_memories.db.metadata import SCHEMA, metadata
from immich_memories.db.tables.annotations import (
    annotation_assets,
    asset_flags,
    asset_people,
    caption_provenance,
    description_fields,
    description_unavailable,
    descriptions,
    face_boxes,
    face_reads,
    head_facts,
    live_clock_offsets,
    motion_bursts,
    motion_lines,
    motion_residuals,
    pixel_facts,
    pixel_facts_thresholds,
    speech_regions,
)
from immich_memories.db.tables.model_answers import (
    editorial_episode_readings,
    editorial_episode_refusals,
    editorial_verdicts,
    judgments,
    library_overviews,
    text_completion_failures,
)
from immich_memories.db.tables.store_meta import store_meta

__all__ = [
    "SCHEMA",
    "annotation_assets",
    "asset_flags",
    "asset_people",
    "caption_provenance",
    "description_fields",
    "description_unavailable",
    "descriptions",
    "editorial_episode_readings",
    "editorial_episode_refusals",
    "editorial_verdicts",
    "face_boxes",
    "face_reads",
    "head_facts",
    "judgments",
    "library_overviews",
    "live_clock_offsets",
    "metadata",
    "motion_bursts",
    "motion_lines",
    "motion_residuals",
    "pixel_facts",
    "pixel_facts_thresholds",
    "speech_regions",
    "store_meta",
    "text_completion_failures",
]
