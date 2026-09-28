"""Alembic environment for the store.

The app runs it through `immich_memories.db.migrate`, which hands over a connection that
already holds the migration lock. Run by the `alembic` CLI (dev only, see `alembic.ini`), it
opens the configured store itself, without the lock.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy.engine import Connection

from immich_memories.db.migrate import migration_options


def _run(connection: Connection, schema: str | None) -> None:
    context.configure(connection=connection, **migration_options(schema))
    with context.begin_transaction():
        context.run_migrations()


def _run_from_cli() -> None:
    from immich_memories.db.bootstrap import resolve_location
    from immich_memories.db.engine import create_store_engine, effective_schema

    location = resolve_location()
    engine = create_store_engine(location)
    try:
        with engine.connect() as connection:
            _run(connection, effective_schema(location))
            connection.commit()
    finally:
        engine.dispose()


if context.is_offline_mode():
    raise SystemExit("the store's migrations run online only")
if (handed := context.config.attributes.get("connection")) is not None:
    _run(handed, context.config.attributes.get("schema"))
else:
    _run_from_cli()
