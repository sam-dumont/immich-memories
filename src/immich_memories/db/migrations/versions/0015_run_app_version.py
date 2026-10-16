"""pipeline_runs.app_version: the release that made the run

Revision ID: 0015_run_app_version
Revises: 0014_run_person_names
Create Date: 2026-10-16

An uploaded film is tagged with the version that made it; older rows keep NULL and their
films go without that tag.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from immich_memories.db.migrate import migration_schema

revision: str = "0015_run_app_version"
down_revision: str | Sequence[str] | None = "0014_run_person_names"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pipeline_runs",
        sa.Column("app_version", sa.String(), nullable=True),
        schema=migration_schema(),
    )


def downgrade() -> None:
    # A plain DROP COLUMN, never batch mode: batch copies the table, and on SQLite dropping
    # the old pipeline_runs cascades into every run's phases, spans and diagnostics.
    op.drop_column("pipeline_runs", "app_version", schema=migration_schema())
