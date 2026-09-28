"""The store's state for `store status`, read without migrating or creating anything."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import sqlalchemy as sa

from immich_memories.db.bootstrap import StoreLocation
from immich_memories.db.inventory import present_counts, recorded_revisions
from immich_memories.db.legacy_import import read_import_record
from immich_memories.db.migrate import heads
from immich_memories.db.network_guard import NetworkFilesystemError, network_filesystem
from immich_memories.db.store import unmigrated_store


@dataclass(frozen=True)
class StoreStatus:
    """Everything `store status` prints."""

    backend: str
    url: str
    schema: str | None
    exists: bool
    revisions: tuple[str, ...] = ()
    at_head: bool = False
    import_record: dict[str, Any] | None = None
    counts: dict[str, int] = field(default_factory=dict)
    size_bytes: int | None = None
    network_filesystem: str | None = None


def store_status(location: StoreLocation) -> StoreStatus:
    """Read the store at `location` as it is. A SQLite file that does not exist is reported."""
    path = location.sqlite_path
    base: dict[str, Any] = {
        "backend": location.dialect_name,
        "url": str(location),
        "schema": location.schema if location.dialect_name == "postgresql" else None,
    }
    if path is not None:
        base["network_filesystem"] = network_filesystem(path)
        if not path.exists():
            return StoreStatus(exists=False, **base)
    try:
        store = unmigrated_store(location)
    except NetworkFilesystemError:
        return StoreStatus(exists=True, **base)
    try:
        with store.connect() as connection:
            revisions = recorded_revisions(connection, store.schema)
            counts = present_counts(connection, store.schema)
            record = read_import_record(connection) if "store_meta" in counts else None
            size = (
                _sqlite_size(path) if path is not None else _schema_size(connection, store.schema)
            )
    finally:
        store.engine.dispose()
    return StoreStatus(
        exists=bool(revisions) or bool(counts),
        revisions=revisions,
        at_head=set(revisions) == set(heads()),
        import_record=record,
        counts=counts,
        size_bytes=size,
        **base,
    )


def _sqlite_size(path: Path) -> int:
    return sum(
        candidate.stat().st_size for candidate in (path, Path(f"{path}-wal")) if candidate.exists()
    )


def _schema_size(connection: sa.Connection, schema: str | None) -> int:
    query = sa.text(
        "SELECT COALESCE(SUM(pg_total_relation_size(c.oid)), 0) FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = :schema AND c.relkind IN ('r', 'm')"
    )
    return int(connection.execute(query, {"schema": schema}).scalar() or 0)
