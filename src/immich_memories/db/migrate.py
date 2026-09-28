"""Run the store's Alembic history, locked, on SQLite or PostgreSQL.

Alembic is driven from here, never from an `alembic.ini`: the history ships inside the
package, and the connection it runs on already holds the migration lock. On PostgreSQL that
lock is a session advisory lock keyed on the schema; on SQLite it is an fcntl lock beside the
file plus `BEGIN IMMEDIATE`, so concurrent starts wait for the first one and then find
nothing left to do.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Connection

from immich_memories.db.engine import SQLITE_BEGIN
from immich_memories.db.metadata import SCHEMA
from immich_memories.db.tables import metadata
from immich_memories.locked_file import file_lock

if TYPE_CHECKING:
    from immich_memories.db.store import Store

FOUNDATION_REVISION = "0001_foundation"
VERSION_TABLE = "alembic_version"
MIGRATIONS_DIR = Path(__file__).parent / "migrations"
# First key of the two-key advisory lock; the second is the schema's hash, so two stores in
# one PostgreSQL database migrate independently.
_PG_LOCK_CLASS = 871_0001


def alembic_config(connection: Connection | None = None, schema: str | None = None) -> Config:
    """An in-memory Alembic config pointing at the packaged history."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.attributes["connection"] = connection
    config.attributes["schema"] = schema
    return config


def script_directory() -> ScriptDirectory:
    return ScriptDirectory.from_config(alembic_config())


def heads() -> tuple[str, ...]:
    """Every head revision of the packaged history."""
    return tuple(sorted(script_directory().get_heads()))


def revision_lineage(revision: str) -> tuple[str, ...]:
    """`revision` and every revision below it, down to base."""
    return tuple(
        script.revision
        for script in script_directory().iterate_revisions(revision, "base")
        if script is not None
    )


def target_metadata(schema: str | None) -> sa.MetaData:
    """The shared metadata with its symbolic schema replaced by the real one.

    Autogenerate reflects through the inspector, which ignores `schema_translate_map`, so it
    has to compare against tables that name the schema they really live in.
    """
    translated = sa.MetaData(naming_convention=metadata.naming_convention)
    # A foreign key's `None` means "keep its schema"; BLANK_SCHEMA is how it says "none".
    referred_to: Any = sa.schema.BLANK_SCHEMA if schema is None else schema

    def referred(_table: Any, _to: Any, _constraint: Any, referred_schema: str | None) -> Any:
        return referred_to if referred_schema == SCHEMA else referred_schema

    for table in metadata.sorted_tables:
        # None takes the target MetaData's schema, which is none; the stubs omit that case.
        table.to_metadata(translated, schema=schema, referred_schema_fn=referred)  # type: ignore[arg-type]
    return translated


def migration_options(schema: str | None) -> dict[str, Any]:
    """`context.configure` options shared by the runner, `env.py` and `pending_changes`."""
    ours = {table.name for table in metadata.sorted_tables}

    def include_name(name: str | None, type_: str, _parents: Any) -> bool:
        if type_ == "schema":
            return name == schema
        if type_ == "table":
            return name in ours
        return True

    def include_object(_obj: Any, name: str | None, type_: str, reflected: bool, _to: Any) -> bool:
        return not (type_ == "table" and reflected and name not in ours)

    return {
        "target_metadata": target_metadata(schema),
        "render_as_batch": True,
        "transactional_ddl": True,
        "version_table": VERSION_TABLE,
        "version_table_schema": schema,
        "include_schemas": schema is not None,
        "include_name": include_name,
        "include_object": include_object,
    }


def migration_schema() -> str | None:
    """The schema a running revision creates and alters tables in; None on SQLite.

    Revisions pass this, never the symbolic `SCHEMA`: Alembic renders ALTER and a batch
    table's rename with the name it is given, past `schema_translate_map`.
    """
    from alembic import op

    return op.get_context().version_table_schema


def _current(connection: Connection, schema: str | None) -> tuple[str, ...]:
    context = MigrationContext.configure(
        connection, opts={"version_table": VERSION_TABLE, "version_table_schema": schema}
    )
    return tuple(sorted(context.get_current_heads()))


def current_revisions(store: Store) -> tuple[str, ...]:
    """The revisions the store's database is at; empty before the first migration."""
    with store.connect() as connection:
        return _current(connection, store.schema)


def pending_changes(store: Store) -> list[Any]:
    """What autogenerate would still emit: empty when tables and migrations agree."""
    with store.connect() as connection:
        context = MigrationContext.configure(connection, opts=migration_options(store.schema))
        return list(compare_metadata(context, context.opts["target_metadata"]))


@contextmanager
def _locked_connection(store: Store) -> Iterator[Connection]:
    if store.dialect_name == "postgresql":
        with store.engine.connect() as connection:
            schema = store.location.schema
            key = {"lock_class": _PG_LOCK_CLASS, "schema": schema}
            connection.execute(
                sa.text("SELECT pg_advisory_lock(:lock_class, hashtext(:schema))"), key
            )
            connection.commit()
            try:
                if not sa.inspect(connection).has_schema(schema):
                    connection.execute(sa.schema.CreateSchema(schema, if_not_exists=True))
                connection.commit()
                yield connection
            finally:
                connection.rollback()
                connection.execute(
                    sa.text("SELECT pg_advisory_unlock(:lock_class, hashtext(:schema))"), key
                )
                connection.commit()
        return
    path = store.location.sqlite_path
    with (
        file_lock(path) if path is not None else nullcontext(),
        store.engine.connect() as connection,
    ):
        yield connection.execution_options(**{SQLITE_BEGIN: "IMMEDIATE"})


def _migrate(store: Store, run: Callable[[Config], None]) -> tuple[str, ...]:
    with _locked_connection(store) as connection:
        before = _current(connection, store.schema)
        connection.commit()
        run(alembic_config(connection, store.schema))
        connection.commit()
        after = _current(connection, store.schema)
        connection.commit()
    below_before = {rev for head in before for rev in revision_lineage(head)}
    return tuple(sorted({rev for head in after for rev in revision_lineage(head)} - below_before))


def upgrade(store: Store) -> tuple[str, ...]:
    """Upgrade to every head under the migration lock; returns the revisions it applied."""
    return _migrate(store, lambda config: command.upgrade(config, "heads"))


def downgrade(store: Store, target: str) -> None:
    """Downgrade to `target` (a revision id or `base`) under the migration lock."""
    _migrate(store, lambda config: command.downgrade(config, target))
