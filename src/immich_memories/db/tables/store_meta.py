"""Small facts about the store itself: import records, one-off flags."""

from __future__ import annotations

from sqlalchemy import JSON, Column, DateTime, String, Table

from immich_memories.db.metadata import metadata

store_meta = Table(
    "store_meta",
    metadata,
    Column("key", String(200), primary_key=True),
    Column("value", JSON, nullable=False),
    Column("updated_at", DateTime, nullable=False),
)
