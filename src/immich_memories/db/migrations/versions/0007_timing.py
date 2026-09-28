"""Run spans and buffered diagnostics.

Revision ID: 0007_timing
Revises: 0006_banks
"""

from typing import Any

import sqlalchemy as sa
from alembic import op

from immich_memories.db.migrate import migration_schema

revision = "0007_timing"
down_revision = "0006_banks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    schema = migration_schema()
    target = f"{schema}.pipeline_runs.run_id" if schema else "pipeline_runs.run_id"
    for table in ("run_spans", "run_diagnostics"):
        columns: list[sa.Column[Any]] = [sa.Column("run_id", sa.String(), nullable=False)]
        keys = ["run_id"]
        if table == "run_spans":
            columns.append(sa.Column("span_id", sa.Integer(), nullable=False))
            keys.append("span_id")
        op.create_table(
            table,
            *columns,
            sa.Column("record", sa.JSON(), nullable=False),
            sa.ForeignKeyConstraint(
                ["run_id"],
                [target],
                name=op.f(f"fk_{table}_run_id_pipeline_runs"),
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint(*keys, name=op.f(f"pk_{table}")),
            schema=schema,
        )


def downgrade() -> None:
    op.drop_table("run_diagnostics", schema=migration_schema())
    op.drop_table("run_spans", schema=migration_schema())
