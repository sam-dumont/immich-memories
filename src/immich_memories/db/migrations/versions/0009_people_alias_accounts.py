"""people_alias_accounts: an alias records the Immich account that can read it

Revision ID: 0009_people_alias_accounts
Revises: 0008_merge_timing_geocoded
Create Date: 2026-09-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from immich_memories.db.migrate import migration_schema

revision: str = "0009_people_alias_accounts"
down_revision: str | Sequence[str] | None = "0008_merge_timing_geocoded"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "people_aliases",
        sa.Column("account", sa.String(), nullable=True),
        schema=migration_schema(),
    )


def downgrade() -> None:
    # SQLite drops a column by copying the table; batch mode does that and is a plain
    # ALTER TABLE on PostgreSQL.
    with op.batch_alter_table("people_aliases", schema=migration_schema()) as batch:
        batch.drop_column("account")
