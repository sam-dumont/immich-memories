"""Phase events as appended rows instead of one rewritten JSON array

Revision ID: 0016_phase_event_rows
Revises: 0015_run_app_version
Create Date: 2026-10-19

Every phase event used to rewrite the run's whole array. The events now live one per row in
`run_phase_events` and `attempt_phase_events`. Upgrading moves each existing array into rows,
in order, and leaves the old column empty, so no run loses an event.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from immich_memories.db.migrate import migration_schema

revision: str = "0016_phase_event_rows"
down_revision: str | Sequence[str] | None = "0015_run_app_version"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BATCH = 500

# (parent table, parent key, event table, event key, event table's foreign-key target)
_PAIRS = (
    ("pipeline_runs", "run_id", "run_phase_events", "run_id"),
    ("automation_attempts", "id", "attempt_phase_events", "attempt_id"),
)


def _create(schema: str | None, parent: str, parent_key: str, name: str, key: str) -> None:
    target = f"{schema}.{parent}.{parent_key}" if schema else f"{parent}.{parent_key}"
    op.create_table(
        name,
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(key, sa.String(), nullable=False),
        sa.Column("event", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            [key],
            [target],
            name=op.f(f"fk_{name}_{key}_{parent}"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{name}")),
        schema=schema,
    )
    op.create_index(op.f(f"ix_{name}_{key}"), name, [key], schema=schema)


def _move_arrays(schema: str | None, parent: str, parent_key: str, name: str, key: str) -> None:
    connection = op.get_bind()
    parents = sa.table(
        parent, sa.column(parent_key), sa.column("phase_events", sa.JSON), schema=schema
    )
    events = sa.table(name, sa.column(key), sa.column("event", sa.JSON), schema=schema)
    held = connection.execute(sa.select(parents.c[parent_key], parents.c.phase_events)).all()
    for owner, array in held:
        if not array:
            continue
        for start in range(0, len(array), _BATCH):
            connection.execute(
                sa.insert(events),
                [{key: owner, "event": event} for event in array[start : start + _BATCH]],
            )
        connection.execute(
            sa.update(parents).where(parents.c[parent_key] == owner).values(phase_events=[])
        )


def upgrade() -> None:
    schema = migration_schema()
    for parent, parent_key, name, key in _PAIRS:
        _create(schema, parent, parent_key, name, key)
        _move_arrays(schema, parent, parent_key, name, key)


def downgrade() -> None:
    # Like every revision's downgrade: the tables this one created go, with their rows. The
    # parent tables are untouched, so their old `phase_events` columns stay empty.
    schema = migration_schema()
    for _parent, _parent_key, name, _key in reversed(_PAIRS):
        op.drop_table(name, schema=schema)
