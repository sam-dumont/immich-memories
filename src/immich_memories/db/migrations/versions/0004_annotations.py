"""annotations: model answers and the owner's decisions move out of annotations.sqlite

Revision ID: 0004_annotations
Revises: 0001_foundation
Create Date: 2026-09-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from immich_memories.db.migrate import migration_schema

revision: str = "0004_annotations"
down_revision: str | Sequence[str] | None = "0001_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "annotation_assets",
        sa.Column("asset_id", sa.Text(), nullable=False),
        sa.Column("taken_at", sa.DateTime(), nullable=True),
        sa.Column("media_kind", sa.Text(), nullable=True),
        sa.Column("favourite", sa.Boolean(), nullable=True),
        sa.Column("original_file", sa.Text(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("city", sa.Text(), nullable=True),
        sa.Column("state", sa.Text(), nullable=True),
        sa.Column("country", sa.Text(), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("live_photo_video_id", sa.Text(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("asset_id", name=op.f("pk_annotation_assets")),
        schema=migration_schema(),
    )
    op.create_table(
        "asset_flags",
        sa.Column("asset_id", sa.Text(), nullable=False),
        sa.Column("flag", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("written_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("asset_id", "flag", "source", name=op.f("pk_asset_flags")),
        schema=migration_schema(),
    )
    op.create_table(
        "asset_people",
        sa.Column("asset_id", sa.Text(), nullable=False),
        sa.Column("person_name", sa.Text(), nullable=False),
        sa.Column("person_id", sa.Text(), nullable=True),
        sa.Column("birth_date", sa.Text(), nullable=True),
        sa.Column("written_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("asset_id", "person_name", name=op.f("pk_asset_people")),
        schema=migration_schema(),
    )
    op.create_table(
        "caption_provenance",
        sa.Column("asset_id", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("asset_id", "model", name=op.f("pk_caption_provenance")),
        schema=migration_schema(),
    )
    op.create_table(
        "description_fields",
        sa.Column("asset_id", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("field", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("written_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("asset_id", "model", "field", name=op.f("pk_description_fields")),
        schema=migration_schema(),
    )
    op.create_table(
        "description_unavailable",
        sa.Column("asset_id", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("producer_key", sa.Text(), nullable=False),
        sa.Column("preview_sha256", sa.Text(), nullable=False),
        sa.Column("image_sha256", sa.Text(), nullable=False),
        sa.Column("request_sha256", sa.Text(), nullable=False),
        sa.Column("request_json", sa.Text(), nullable=False),
        sa.Column("attempts_json", sa.Text(), nullable=False),
        sa.Column("written_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("asset_id", "model", name=op.f("pk_description_unavailable")),
        schema=migration_schema(),
    )
    op.create_table(
        "descriptions",
        sa.Column("asset_id", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("written_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("asset_id", "model", name=op.f("pk_descriptions")),
        schema=migration_schema(),
    )
    op.create_table(
        "editorial_episode_readings",
        sa.Column("group_id", sa.Text(), nullable=False),
        sa.Column("producer_key", sa.Text(), nullable=False),
        sa.Column("evidence_key", sa.Text(), nullable=False),
        sa.Column("full_asset_ids", sa.Text(), nullable=False),
        sa.Column("what_happened", sa.Text(), nullable=False),
        sa.Column("representatives", sa.Text(), nullable=False),
        sa.Column("cull_decisions", sa.Text(), nullable=False),
        sa.Column("notable_moments", sa.Text(), nullable=False),
        sa.Column("answered_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint(
            "group_id", "producer_key", "evidence_key", name=op.f("pk_editorial_episode_readings")
        ),
        schema=migration_schema(),
    )
    op.create_table(
        "editorial_episode_refusals",
        sa.Column("group_id", sa.Text(), nullable=False),
        sa.Column("producer_key", sa.Text(), nullable=False),
        sa.Column("evidence_key", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("answered_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint(
            "group_id", "producer_key", "evidence_key", name=op.f("pk_editorial_episode_refusals")
        ),
        schema=migration_schema(),
    )
    op.create_table(
        "editorial_verdicts",
        sa.Column("asset_id", sa.Text(), nullable=False),
        sa.Column("pass_version", sa.Text(), nullable=False),
        sa.Column("bucket", sa.Text(), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("asset_id", "pass_version", name=op.f("pk_editorial_verdicts")),
        schema=migration_schema(),
    )
    op.create_table(
        "face_boxes",
        sa.Column("asset_id", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("named", sa.Boolean(), nullable=True),
        sa.Column("x1", sa.Float(), nullable=True),
        sa.Column("y1", sa.Float(), nullable=True),
        sa.Column("x2", sa.Float(), nullable=True),
        sa.Column("y2", sa.Float(), nullable=True),
        sa.Column("person_id", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("asset_id", "ordinal", name=op.f("pk_face_boxes")),
        schema=migration_schema(),
    )
    op.create_table(
        "face_reads",
        sa.Column("asset_id", sa.Text(), nullable=False),
        sa.Column("producer", sa.Text(), nullable=False),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("asset_id", "producer", name=op.f("pk_face_reads")),
        schema=migration_schema(),
    )
    op.create_table(
        "head_facts",
        sa.Column("asset_id", sa.Text(), nullable=False),
        sa.Column("head", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("encoder_key", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("asset_id", "head", "version", name=op.f("pk_head_facts")),
        schema=migration_schema(),
    )
    op.create_table(
        "judgments",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("answered_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_judgments")),
        schema=migration_schema(),
    )
    op.create_index(
        op.f("ix_judgments_answered_at"),
        "judgments",
        ["answered_at"],
        unique=False,
        schema=migration_schema(),
    )
    op.create_table(
        "library_overviews",
        sa.Column("node_key", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("period", sa.Text(), nullable=False),
        sa.Column("account", sa.Text(), nullable=False),
        sa.Column("children", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("node_key", name=op.f("pk_library_overviews")),
        schema=migration_schema(),
    )
    op.create_table(
        "live_clock_offsets",
        sa.Column("asset_id", sa.Text(), nullable=False),
        sa.Column("producer", sa.Text(), nullable=False),
        sa.Column("source_digest", sa.Text(), nullable=False),
        sa.Column("measured", sa.Text(), nullable=False),
        sa.Column("written_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("asset_id", "producer", name=op.f("pk_live_clock_offsets")),
        schema=migration_schema(),
    )
    op.create_table(
        "motion_bursts",
        sa.Column("asset_id", sa.Text(), nullable=False),
        sa.Column("burst_id", sa.Text(), nullable=True),
        sa.Column("still_ids", sa.Text(), nullable=True),
        sa.Column("video_ids", sa.Text(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("beats_a_still", sa.Boolean(), nullable=True),
        sa.Column("minimum_seconds", sa.Float(), nullable=True),
        sa.Column("computed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("asset_id", name=op.f("pk_motion_bursts")),
        schema=migration_schema(),
    )
    op.create_table(
        "motion_lines",
        sa.Column("asset_id", sa.Text(), nullable=False),
        sa.Column("producer", sa.Text(), nullable=False),
        sa.Column("source_digest", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("frames", sa.Integer(), nullable=False),
        sa.Column("bytes_read", sa.Integer(), nullable=False),
        sa.Column("written_at", sa.DateTime(), nullable=False),
        sa.Column("provenance", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("asset_id", "producer", name=op.f("pk_motion_lines")),
        schema=migration_schema(),
    )
    op.create_table(
        "motion_residuals",
        sa.Column("asset_id", sa.Text(), nullable=False),
        sa.Column("producer", sa.Text(), nullable=False),
        sa.Column("source_digest", sa.Text(), nullable=False),
        sa.Column("measured", sa.Text(), nullable=False),
        sa.Column("written_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("asset_id", "producer", name=op.f("pk_motion_residuals")),
        schema=migration_schema(),
    )
    op.create_table(
        "pixel_facts",
        sa.Column("asset_id", sa.Text(), nullable=False),
        sa.Column("producer_key", sa.Text(), nullable=True),
        sa.Column("sharpness", sa.Float(), nullable=True),
        sa.Column("brightness", sa.Float(), nullable=True),
        sa.Column("contrast", sa.Float(), nullable=True),
        sa.Column("dark_fraction", sa.Float(), nullable=True),
        sa.Column("bright_fraction", sa.Float(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("orientation", sa.Text(), nullable=True),
        sa.Column("needs_rotation", sa.Boolean(), nullable=True),
        sa.Column("computed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("asset_id", name=op.f("pk_pixel_facts")),
        schema=migration_schema(),
    )
    op.create_table(
        "pixel_facts_thresholds",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("producer_key", sa.Text(), nullable=True),
        sa.Column("n", sa.Integer(), nullable=True),
        sa.Column("computed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("name", name=op.f("pk_pixel_facts_thresholds")),
        schema=migration_schema(),
    )
    op.create_table(
        "speech_regions",
        sa.Column("asset_id", sa.Text(), nullable=False),
        sa.Column("producer", sa.Text(), nullable=False),
        sa.Column("source_digest", sa.Text(), nullable=False),
        sa.Column("measured", sa.Text(), nullable=False),
        sa.Column("written_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("asset_id", "producer", name=op.f("pk_speech_regions")),
        schema=migration_schema(),
    )
    op.create_table(
        "text_completion_failures",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("record", sa.Text(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_text_completion_failures")),
        schema=migration_schema(),
    )


def downgrade() -> None:
    op.drop_table("text_completion_failures", schema=migration_schema())
    op.drop_table("speech_regions", schema=migration_schema())
    op.drop_table("pixel_facts_thresholds", schema=migration_schema())
    op.drop_table("pixel_facts", schema=migration_schema())
    op.drop_table("motion_residuals", schema=migration_schema())
    op.drop_table("motion_lines", schema=migration_schema())
    op.drop_table("motion_bursts", schema=migration_schema())
    op.drop_table("live_clock_offsets", schema=migration_schema())
    op.drop_table("library_overviews", schema=migration_schema())
    op.drop_index(
        op.f("ix_judgments_answered_at"), table_name="judgments", schema=migration_schema()
    )
    op.drop_table("judgments", schema=migration_schema())
    op.drop_table("head_facts", schema=migration_schema())
    op.drop_table("face_reads", schema=migration_schema())
    op.drop_table("face_boxes", schema=migration_schema())
    op.drop_table("editorial_verdicts", schema=migration_schema())
    op.drop_table("editorial_episode_refusals", schema=migration_schema())
    op.drop_table("editorial_episode_readings", schema=migration_schema())
    op.drop_table("descriptions", schema=migration_schema())
    op.drop_table("description_unavailable", schema=migration_schema())
    op.drop_table("description_fields", schema=migration_schema())
    op.drop_table("caption_provenance", schema=migration_schema())
    op.drop_table("asset_people", schema=migration_schema())
    op.drop_table("asset_flags", schema=migration_schema())
    op.drop_table("annotation_assets", schema=migration_schema())
