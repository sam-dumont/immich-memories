"""Settings saved from the UI or the CLI: one row per runtime key path, below env and config.yaml."""

from __future__ import annotations

from sqlalchemy import JSON, Boolean, Column, DateTime, LargeBinary, String, Table

from immich_memories.db.metadata import metadata

# `key` is the runtime path (`llm.model`, never `advanced.llm.model`). A secret row keeps
# `value` null and its Fernet token in `ciphertext`.
settings = Table(
    "settings",
    metadata,
    Column("key", String(), primary_key=True),
    Column("value", JSON, nullable=True),
    Column("secret", Boolean, nullable=False),
    Column("ciphertext", LargeBinary, nullable=True),
    Column("updated_at", DateTime, nullable=False),
)
