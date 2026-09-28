"""The store: one versioned database on SQLite (default) or PostgreSQL (#871).

See docs/designs/2026-09-27-the-store.md for the contract every table follows.
"""

from immich_memories.db.bootstrap import StoreLocation, redact_url, resolve_location
from immich_memories.db.migrate import (
    FOUNDATION_REVISION,
    current_revisions,
    downgrade,
    heads,
    migration_schema,
    pending_changes,
    revision_lineage,
    upgrade,
)
from immich_memories.db.network_guard import (
    NetworkFilesystemError,
    guard_sqlite_path,
    network_filesystem,
)
from immich_memories.db.sqlite_files import connect_sqlite, private_database_path
from immich_memories.db.store import Store, close_stores, open_store
from immich_memories.db.time import from_db, iso_from_db, now_db, to_db
from immich_memories.db.upsert import upsert

__all__ = [
    "FOUNDATION_REVISION",
    "NetworkFilesystemError",
    "Store",
    "StoreLocation",
    "close_stores",
    "connect_sqlite",
    "current_revisions",
    "downgrade",
    "from_db",
    "guard_sqlite_path",
    "heads",
    "iso_from_db",
    "migration_schema",
    "network_filesystem",
    "now_db",
    "open_store",
    "pending_changes",
    "private_database_path",
    "redact_url",
    "resolve_location",
    "revision_lineage",
    "to_db",
    "upgrade",
    "upsert",
]
