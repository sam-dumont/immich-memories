"""banks: the audience bank, the block vote banks and the owner's review edits leave JSON files

Revision ID: 0006_banks
Revises: 0005_operations
Create Date: 2026-09-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from immich_memories.db.migrate import migration_schema

revision: str = "0006_banks"
down_revision: str | Sequence[str] | None = "0005_operations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audience_answers",
        sa.Column("answerer", sa.Text(), nullable=False),
        sa.Column("evidence_key", sa.Text(), nullable=False),
        sa.Column("record", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("answerer", "evidence_key", name=op.f("pk_audience_answers")),
        schema=migration_schema(),
    )
    op.create_table(
        "audience_holds",
        sa.Column("asset_id", sa.Text(), nullable=False),
        sa.Column("slot", sa.Text(), nullable=False),
        sa.Column("hold", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("asset_id", "slot", name=op.f("pk_audience_holds")),
        schema=migration_schema(),
    )
    op.create_table(
        "vote_bank_entries",
        sa.Column("bank", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("section", sa.Text(), nullable=False),
        sa.Column("entry_key", sa.Text(), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint(
            "bank", "scope", "section", "entry_key", name=op.f("pk_vote_bank_entries")
        ),
        schema=migration_schema(),
    )
    op.create_table(
        "owner_edits",
        sa.Column("edit_id", sa.Text(), nullable=False),
        sa.Column("film_stem", sa.Text(), nullable=False),
        sa.Column("attempt_id", sa.Text(), nullable=True),
        sa.Column("record", sa.JSON(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("edit_id", name=op.f("pk_owner_edits")),
        schema=migration_schema(),
    )
    op.create_index(
        op.f("ix_owner_edits_attempt_id"),
        "owner_edits",
        ["attempt_id"],
        unique=False,
        schema=migration_schema(),
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_owner_edits_attempt_id"), table_name="owner_edits", schema=migration_schema()
    )
    op.drop_table("owner_edits", schema=migration_schema())
    op.drop_table("vote_bank_entries", schema=migration_schema())
    op.drop_table("audience_holds", schema=migration_schema())
    op.drop_table("audience_answers", schema=migration_schema())
