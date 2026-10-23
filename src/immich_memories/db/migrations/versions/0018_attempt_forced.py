"""automation_attempts.forced: a run started on purpose doesn't pace the scheduled ones

Revision ID: 0018_attempt_forced
Revises: 0017_episode_refusal_answers
Create Date: 2026-10-23

A film made with `auto run --force` or Run this suggestion counted toward the cooldown and the
daily timer like a scheduled one, so the next scheduled run was skipped. Each new attempt says
whether it was forced; older rows keep NULL and count as they always did.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from immich_memories.db.migrate import migration_schema

revision: str = "0018_attempt_forced"
down_revision: str | Sequence[str] | None = "0017_episode_refusal_answers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "automation_attempts",
        sa.Column("forced", sa.Boolean(), nullable=True),
        schema=migration_schema(),
    )


def downgrade() -> None:
    # A plain DROP COLUMN, never batch mode, like every column this store drops.
    op.drop_column("automation_attempts", "forced", schema=migration_schema())
