"""What a legacy importer did, and the records `store_meta` keeps of completed imports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from immich_memories.db.tables.store_meta import store_meta
from immich_memories.db.time import now_db
from immich_memories.db.upsert import upsert


@dataclass(frozen=True)
class ImportOutcome:
    """One legacy source's import: records taken, records left alone, and why."""

    source: str
    imported: int
    skipped: int
    notes: tuple[str, ...] = ()


# The `store_meta` key of the record a completed legacy import leaves; one per importer below it.
IMPORT_RECORD = "legacy_import"


def importer_record_key(name: str) -> str:
    """The `store_meta` key where one importer's completed run is recorded."""
    return f"{IMPORT_RECORD}:{name}"


def read_import_record(connection: Connection, key: str = IMPORT_RECORD) -> dict[str, Any] | None:
    """The recorded import at `key` (the whole import by default), or None."""
    value = connection.execute(
        sa.select(store_meta.c.value).where(store_meta.c.key == key)
    ).scalar()
    return value if isinstance(value, dict) else None


def write_import_record(connection: Connection, key: str, value: dict[str, Any]) -> None:
    """Record `value` at `key`, replacing an older record."""
    upsert(connection, store_meta, [{"key": key, "value": value, "updated_at": now_db()}], ["key"])
