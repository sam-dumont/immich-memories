"""people_groups: a saved label plus an expression over canonical person ids

Revision ID: 0011_people_groups
Revises: 0010_run_film_timeline
Create Date: 2026-09-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from immich_memories.db.migrate import migration_schema

revision: str = "0011_people_groups"
down_revision: str | Sequence[str] | None = "0010_run_film_timeline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "people_groups",
        sa.Column("label", sa.String(), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("expression", sa.JSON(), nullable=False),
        schema=migration_schema(),
    )


def downgrade() -> None:
    op.drop_table("people_groups", schema=migration_schema())
