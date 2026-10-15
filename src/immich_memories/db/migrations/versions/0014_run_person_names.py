"""pipeline_runs.person_names: every person a run was about, not only the first

Revision ID: 0014_run_person_names
Revises: 0013_session_generations
Create Date: 2026-10-15

Older rows keep NULL here and read as their one `person_name`.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from immich_memories.db.migrate import migration_schema

revision: str = "0014_run_person_names"
down_revision: str | Sequence[str] | None = "0013_session_generations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pipeline_runs",
        sa.Column("person_names", sa.JSON(), nullable=True),
        schema=migration_schema(),
    )


def downgrade() -> None:
    # A plain DROP COLUMN, never batch mode: batch copies the table, and on SQLite dropping
    # the old pipeline_runs cascades into every run's phases, spans and diagnostics.
    op.drop_column("pipeline_runs", "person_names", schema=migration_schema())
