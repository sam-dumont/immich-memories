"""session_generations: one atomic integer row per revocation key

Revision ID: 0013_session_generations
Revises: 0012_annotation_assets_is_edited
Create Date: 2026-10-08

The counts lived in one `store_meta` JSON dict the app read, changed and wrote back;
two concurrent sign-outs on PostgreSQL both read the same dict and the second write
dropped the first's revocation. Integer rows bumped by a single INSERT .. ON
CONFLICT statement cannot lose a bump. Existing counts are copied forward so an
upgrade never resurrects a cookie a sign-out had already ended.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

from immich_memories.db.migrate import migration_schema
from immich_memories.db.time import to_db

revision: str = "0013_session_generations"
down_revision: str | Sequence[str] | None = "0012_annotation_assets_is_edited"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LEGACY_KEY = "auth.session_generations"


def upgrade() -> None:
    schema = migration_schema()
    op.create_table(
        "session_generations",
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        schema=schema,
    )
    # Typed expressions quote the schema and adapt JSON/datetimes on both backends.
    store = sa.table(
        "store_meta", sa.column("key", sa.String()), sa.column("value", sa.JSON()), schema=schema
    )
    generations = sa.table(
        "session_generations",
        sa.column("key", sa.String()),
        sa.column("generation", sa.Integer()),
        sa.column("updated_at", sa.DateTime()),
        schema=schema,
    )
    bind = op.get_bind()
    legacy = bind.execute(sa.select(store.c.value).where(store.c.key == _LEGACY_KEY)).scalar()
    if isinstance(legacy, dict):
        rows = [
            {"key": key, "generation": count, "updated_at": to_db(datetime.now(UTC))}
            for key, count in legacy.items()
            if isinstance(count, int)
        ]
        if rows:
            bind.execute(sa.insert(generations), rows)
        bind.execute(sa.delete(store).where(store.c.key == _LEGACY_KEY))


def downgrade() -> None:
    op.drop_table("session_generations", schema=migration_schema())
