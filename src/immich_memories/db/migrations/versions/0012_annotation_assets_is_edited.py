"""annotation_assets.is_edited: whether Immich's own editor last touched this asset

Revision ID: 0012_annotation_assets_is_edited
Revises: 0011_people_groups
Create Date: 2026-10-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from immich_memories.db.migrate import migration_schema

revision: str = "0012_annotation_assets_is_edited"
down_revision: str | Sequence[str] | None = "0011_people_groups"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "annotation_assets",
        sa.Column("is_edited", sa.Boolean(), nullable=True),
        schema=migration_schema(),
    )


def downgrade() -> None:
    # A plain DROP COLUMN, never batch mode: see 0010_run_film_timeline.
    op.drop_column("annotation_assets", "is_edited", schema=migration_schema())
