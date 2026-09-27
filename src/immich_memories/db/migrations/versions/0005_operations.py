"""operations: run history, automation attempts, notification health, asset scores, special days

Revision ID: 0005_operations
Revises: 0004_annotations
Create Date: 2026-09-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from immich_memories.db.migrate import migration_schema

revision: str = "0005_operations"
down_revision: str | Sequence[str] | None = "0004_annotations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEXES = (
    ("asset_scores", ("asset_type",)),
    ("automation_attempts", ("started_at",)),
    ("pipeline_runs", ("automation_attempt_id",)),
    ("pipeline_runs", ("created_at",)),
    ("pipeline_runs", ("delivery_status", "source", "status")),
    ("pipeline_runs", ("memory_key",)),
    ("pipeline_runs", ("status",)),
    ("phase_stats", ("run_id",)),
)


def _index_name(table: str, columns: tuple[str, ...]) -> str:
    return f"ix_{table}_{'_'.join(columns)}"


def _create_run_tables(schema: str | None) -> None:
    op.create_table(
        "pipeline_runs",
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("memory_type", sa.String(), nullable=True),
        sa.Column("memory_key", sa.String(), nullable=True),
        sa.Column("memory_category", sa.String(), nullable=True),
        sa.Column("memory_people", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("automation_attempt_id", sa.String(), nullable=True),
        sa.Column("last_phase", sa.String(), nullable=True),
        sa.Column("phase_events", sa.JSON(), nullable=False),
        sa.Column("person_name", sa.Text(), nullable=True),
        sa.Column("person_id", sa.String(), nullable=True),
        sa.Column("date_range_start", sa.String(), nullable=True),
        sa.Column("date_range_end", sa.String(), nullable=True),
        sa.Column("target_duration_seconds", sa.Integer(), nullable=True),
        sa.Column("output_path", sa.Text(), nullable=True),
        sa.Column("output_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("output_duration_seconds", sa.Float(), nullable=False),
        sa.Column("clips_analyzed", sa.Integer(), nullable=False),
        sa.Column("clips_selected", sa.Integer(), nullable=False),
        sa.Column("errors_count", sa.Integer(), nullable=False),
        sa.Column("system_info", sa.JSON(), nullable=True),
        sa.Column("delivery_status", sa.String(), nullable=False),
        sa.Column("delivery_attempts", sa.Integer(), nullable=False),
        sa.Column("delivery_error", sa.Text(), nullable=True),
        sa.Column("immich_asset_id", sa.String(), nullable=True),
        sa.Column("delivery_album", sa.Text(), nullable=True),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("llm_metrics", sa.JSON(), nullable=True),
        sa.Column("title_source", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("run_id", name=op.f("pk_pipeline_runs")),
        schema=schema,
    )
    target = f"{schema}.pipeline_runs.run_id" if schema else "pipeline_runs.run_id"
    op.create_table(
        "phase_stats",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("phase_name", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("items_processed", sa.Integer(), nullable=False),
        sa.Column("items_total", sa.Integer(), nullable=False),
        sa.Column("errors", sa.JSON(), nullable=True),
        sa.Column("extra_metrics", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["run_id"],
            [target],
            name=op.f("fk_phase_stats_run_id_pipeline_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_phase_stats")),
        schema=schema,
    )
    op.create_table(
        "run_attempts",
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("attempt_dir", sa.Text(), nullable=False),
        sa.Column("output_path", sa.Text(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("run_id", name=op.f("pk_run_attempts")),
        schema=schema,
    )


def _create_automation_tables(schema: str | None) -> None:
    op.create_table(
        "automation_attempts",
        sa.Column("seq", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("candidate_category", sa.String(), nullable=True),
        sa.Column("memory_type", sa.String(), nullable=True),
        sa.Column("memory_key", sa.String(), nullable=True),
        sa.Column("run_id", sa.String(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("last_phase", sa.String(), nullable=True),
        sa.Column("phase_events", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("seq", name=op.f("pk_automation_attempts")),
        sa.UniqueConstraint("id", name=op.f("uq_automation_attempts_id")),
        schema=schema,
    )
    op.create_table(
        "notification_health",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(), nullable=True),
        sa.Column("failure_category", sa.String(), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_health")),
        schema=schema,
    )
    op.create_table(
        "special_days",
        sa.Column("position", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("record", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("position", name=op.f("pk_special_days")),
        schema=schema,
    )


def _create_asset_scores(schema: str | None) -> None:
    op.create_table(
        "asset_scores",
        sa.Column("asset_id", sa.String(), nullable=False),
        sa.Column("model_version", sa.String(), nullable=False),
        sa.Column("asset_type", sa.String(), nullable=False),
        sa.Column("llm_interest", sa.Float(), nullable=True),
        sa.Column("llm_quality", sa.Float(), nullable=True),
        sa.Column("llm_emotion", sa.Text(), nullable=True),
        sa.Column("llm_description", sa.Text(), nullable=True),
        sa.Column("llm_category", sa.String(), nullable=True),
        sa.Column("metadata_score", sa.Float(), nullable=False),
        sa.Column("combined_score", sa.Float(), nullable=False),
        sa.Column("analyzed_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("asset_id", "model_version", name=op.f("pk_asset_scores")),
        schema=schema,
    )


def upgrade() -> None:
    schema = migration_schema()
    _create_run_tables(schema)
    _create_automation_tables(schema)
    _create_asset_scores(schema)
    for table, columns in _INDEXES:
        op.create_index(
            op.f(_index_name(table, columns)), table, list(columns), unique=False, schema=schema
        )


def downgrade() -> None:
    schema = migration_schema()
    for table, columns in reversed(_INDEXES):
        op.drop_index(op.f(_index_name(table, columns)), table_name=table, schema=schema)
    for table in (
        "phase_stats",
        "run_attempts",
        "pipeline_runs",
        "automation_attempts",
        "notification_health",
        "special_days",
        "asset_scores",
    ):
        op.drop_table(table, schema=schema)
