"""Every store table, registered on the shared `metadata` by importing its module here.

A new domain adds `db/tables/<domain>.py`, imports it below, and ships an Alembic revision
creating what it declares; `tests/store/test_migrations.py` fails until the two agree.
"""

from immich_memories.db.metadata import SCHEMA, metadata
from immich_memories.db.tables.operations import (
    asset_scores,
    automation_attempts,
    notification_health,
    phase_stats,
    pipeline_runs,
    run_attempts,
    special_days,
)
from immich_memories.db.tables.store_meta import store_meta

__all__ = [
    "SCHEMA",
    "asset_scores",
    "automation_attempts",
    "metadata",
    "notification_health",
    "phase_stats",
    "pipeline_runs",
    "run_attempts",
    "special_days",
    "store_meta",
]
