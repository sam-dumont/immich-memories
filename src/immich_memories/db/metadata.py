"""The one `MetaData` every store table is declared on.

Tables name the symbolic schema `immich_memories`. The engine translates it: to nothing on
SQLite, to the configured schema on PostgreSQL. So a table is written once for both backends,
and a PostgreSQL store can live in any schema, even inside Immich's own database.
"""

from __future__ import annotations

from sqlalchemy import MetaData

SCHEMA = "immich_memories"

# Named constraints: SQLite batch migrations recreate tables, and they can only drop or alter
# a constraint they can name the same way on both backends.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(schema=SCHEMA, naming_convention=NAMING_CONVENTION)
