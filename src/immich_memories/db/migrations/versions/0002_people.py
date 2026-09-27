"""people: the people registry moves out of people.yaml

Revision ID: 0002_people
Revises: 0001_foundation
Create Date: 2026-09-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from immich_memories.db.migrate import migration_schema

revision: str = "0002_people"
down_revision: str | Sequence[str] | None = "0001_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _person_fk(table: str) -> sa.ForeignKeyConstraint:
    schema = migration_schema()
    target = f"{schema}.people.person_id" if schema else "people.person_id"
    return sa.ForeignKeyConstraint(
        ["person_id"],
        [target],
        name=op.f(f"fk_{table}_person_id_people"),
        ondelete="CASCADE",
    )


def upgrade() -> None:
    schema = migration_schema()
    op.create_table(
        "people_registry",
        sa.Column("registry", sa.String(), nullable=False),
        sa.Column("header", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("registry", name=op.f("pk_people_registry")),
        schema=schema,
    )
    op.create_table(
        "people",
        sa.Column("person_id", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("birth_date", sa.String(), nullable=True),
        sa.Column("origin", sa.String(), nullable=True),
        sa.Column("inferred", sa.JSON(), nullable=True),
        sa.Column("confirmed", sa.JSON(), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("person_id", name=op.f("pk_people")),
        schema=schema,
    )
    op.create_table(
        "people_aliases",
        sa.Column("alias_id", sa.String(), nullable=False),
        sa.Column("person_id", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        _person_fk("people_aliases"),
        sa.PrimaryKeyConstraint("alias_id", name=op.f("pk_people_aliases")),
        schema=schema,
    )
    op.create_index(
        op.f("ix_people_aliases_person_id"),
        "people_aliases",
        ["person_id"],
        unique=False,
        schema=schema,
    )
    op.create_table(
        "people_relationships",
        sa.Column("person_id", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=True),
        sa.Column("target_id", sa.String(), nullable=True),
        sa.Column("reverse", sa.String(), nullable=True),
        sa.Column("decision", sa.String(), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=True),
        _person_fk("people_relationships"),
        sa.PrimaryKeyConstraint("person_id", "position", name=op.f("pk_people_relationships")),
        schema=schema,
    )
    op.create_index(
        op.f("ix_people_relationships_target_id"),
        "people_relationships",
        ["target_id"],
        unique=False,
        schema=schema,
    )


def downgrade() -> None:
    schema = migration_schema()
    op.drop_index(
        op.f("ix_people_relationships_target_id"), table_name="people_relationships", schema=schema
    )
    op.drop_table("people_relationships", schema=schema)
    op.drop_index(op.f("ix_people_aliases_person_id"), table_name="people_aliases", schema=schema)
    op.drop_table("people_aliases", schema=schema)
    op.drop_table("people", schema=schema)
    op.drop_table("people_registry", schema=schema)
