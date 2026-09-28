"""geocoded_places: the reverse-geocode cache, one row per coordinate cell and language

Revision ID: 0007_geocoded_places
Revises: 0006_banks
Create Date: 2026-09-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from immich_memories.db.migrate import migration_schema

revision: str = "0007_geocoded_places"
down_revision: str | Sequence[str] | None = "0006_banks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "geocoded_places",
        sa.Column("cell", sa.String(), nullable=False),
        sa.Column("language", sa.String(), nullable=False),
        sa.Column("address", sa.JSON(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("cell", "language", name=op.f("pk_geocoded_places")),
        schema=migration_schema(),
    )


def downgrade() -> None:
    op.drop_table("geocoded_places", schema=migration_schema())
