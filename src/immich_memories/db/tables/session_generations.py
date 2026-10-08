"""Session revocation generations: one integer row per key, bumped atomically in SQL.

A JSON dict shared by every writer lost updates under concurrent transactions on
PostgreSQL; one integer row per key bumped by a single INSERT .. ON CONFLICT statement
cannot. `key` is `*` for everyone or a username; the column never holds anything a
cookie carries, only the count a cookie must match.
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, Integer, String, Table

from immich_memories.db.metadata import metadata

session_generations = Table(
    "session_generations",
    metadata,
    Column("key", String(), primary_key=True),
    Column("generation", Integer(), nullable=False),
    Column("updated_at", DateTime, nullable=False),
)
