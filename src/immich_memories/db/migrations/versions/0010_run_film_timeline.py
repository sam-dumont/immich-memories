"""pipeline_runs.film_timeline: a run's content, title and map-extra seconds

Revision ID: 0010_run_film_timeline
Revises: 0009_people_alias_accounts
Create Date: 2026-09-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from immich_memories.db.migrate import migration_schema

revision: str = "0010_run_film_timeline"
down_revision: str | Sequence[str] | None = "0009_people_alias_accounts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pipeline_runs",
        sa.Column("film_timeline", sa.JSON(), nullable=True),
        schema=migration_schema(),
    )


def downgrade() -> None:
    # A plain DROP COLUMN, never batch mode: batch copies the table, and on SQLite dropping
    # the old pipeline_runs cascades into every run's phases, spans and diagnostics.
    # SQLite has dropped a column in place since 3.35.
    op.drop_column("pipeline_runs", "film_timeline", schema=migration_schema())
