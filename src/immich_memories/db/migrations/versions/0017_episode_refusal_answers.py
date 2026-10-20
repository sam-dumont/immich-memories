"""editorial_episode_refusals.answer_excerpt: what the reader actually answered

Revision ID: 0017_episode_refusal_answers
Revises: 0016_phase_event_rows
Create Date: 2026-10-20

A refusal kept only its reason, so a later run that reports the episode as unread again could
not say what the reader had written. Each new refusal keeps a bounded excerpt of the answer it
was filed over; older rows keep NULL.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from immich_memories.db.migrate import migration_schema

revision: str = "0017_episode_refusal_answers"
down_revision: str | Sequence[str] | None = "0016_phase_event_rows"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "editorial_episode_refusals",
        sa.Column("answer_excerpt", sa.Text(), nullable=True),
        schema=migration_schema(),
    )


def downgrade() -> None:
    # A plain DROP COLUMN, never batch mode, like every column this store drops.
    op.drop_column("editorial_episode_refusals", "answer_excerpt", schema=migration_schema())
