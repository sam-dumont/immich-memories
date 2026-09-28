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
from immich_memories.db.tables.banks import (
    audience_answers,
    audience_holds,
    owner_edits,
    vote_bank_entries,
)
from immich_memories.db.tables.model_answers import (
    editorial_episode_readings,
    editorial_episode_refusals,
    editorial_verdicts,
    judgments,
    library_overviews,
    text_completion_failures,
)
from immich_memories.db.tables.operations import (
    asset_scores,
    automation_attempts,
    notification_health,
    phase_stats,
    pipeline_runs,
    run_attempts,
    special_days,
)
from immich_memories.db.tables.people import (
    people,
    people_aliases,
    people_registry,
    people_relationships,
)
from immich_memories.db.tables.places import geocoded_places
from immich_memories.db.tables.settings import settings
from immich_memories.db.tables.store_meta import store_meta
from immich_memories.db.tables.timing import run_diagnostics, run_spans

__all__ = [
    "SCHEMA",
    "annotation_assets",
    "asset_flags",
    "asset_people",
    "asset_scores",
    "audience_answers",
    "audience_holds",
    "automation_attempts",
    "caption_provenance",
    "description_fields",
    "description_unavailable",
    "descriptions",
    "editorial_episode_readings",
    "editorial_episode_refusals",
    "editorial_verdicts",
    "face_boxes",
    "face_reads",
    "geocoded_places",
    "head_facts",
    "judgments",
    "library_overviews",
    "live_clock_offsets",
    "metadata",
    "motion_bursts",
    "motion_lines",
    "motion_residuals",
    "notification_health",
    "owner_edits",
    "people",
    "people_aliases",
    "people_registry",
    "people_relationships",
    "phase_stats",
    "pipeline_runs",
    "pixel_facts",
    "pixel_facts_thresholds",
    "run_attempts",
    "run_diagnostics",
    "run_spans",
    "settings",
    "special_days",
    "speech_regions",
    "store_meta",
    "text_completion_failures",
    "vote_bank_entries",
]
