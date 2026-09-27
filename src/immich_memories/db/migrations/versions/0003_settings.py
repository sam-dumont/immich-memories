"""settings: the keys saved from the UI or the CLI, secrets encrypted

Revision ID: 0003_settings
Revises: 0002_people
Create Date: 2026-09-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from immich_memories.db.migrate import migration_schema

revision: str = "0003_settings"
down_revision: str | Sequence[str] | None = "0002_people"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "settings",
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("value", sa.JSON(), nullable=True),
        sa.Column("secret", sa.Boolean(), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_settings")),
        schema=migration_schema(),
    )


def downgrade() -> None:
    op.drop_table("settings", schema=migration_schema())
