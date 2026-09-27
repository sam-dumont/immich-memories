"""Every store table, registered on the shared `metadata` by importing its module here.

A new domain adds `db/tables/<domain>.py`, imports it below, and ships an Alembic revision
creating what it declares; `tests/store/test_migrations.py` fails until the two agree.
"""

from immich_memories.db.metadata import SCHEMA, metadata
from immich_memories.db.tables.settings import settings
from immich_memories.db.tables.store_meta import store_meta

__all__ = ["SCHEMA", "metadata", "settings", "store_meta"]
