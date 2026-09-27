"""One Alembic history, upgraded on open, reversible, and scoped to our schema."""

from __future__ import annotations

import sqlalchemy as sa

from immich_memories.db import (
    FOUNDATION_REVISION,
    current_revisions,
    downgrade,
    heads,
    open_store,
    pending_changes,
    revision_lineage,
)
from immich_memories.db.tables import metadata


def _tables(store) -> set[str]:
    with store.connect() as connection:
        return set(sa.inspect(connection).get_table_names(schema=store.schema))


def test_opening_a_fresh_store_migrates_it_to_head(store):
    assert set(current_revisions(store)) == set(heads())
    assert {table.name for table in metadata.sorted_tables} <= _tables(store)
    assert FOUNDATION_REVISION in store.applied


def test_opening_it_again_applies_nothing(location):
    open_store(location=location)
    from immich_memories.db import close_stores

    close_stores()

    assert open_store(location=location).applied == ()


def test_the_declared_tables_match_what_the_migrations_built(store):
    assert pending_changes(store) == []


def test_the_history_goes_down_to_base_and_back_up(store):
    downgrade(store, "base")

    assert current_revisions(store) == ()
    assert not ({table.name for table in metadata.sorted_tables} & _tables(store))

    from immich_memories.db import upgrade

    upgrade(store)

    assert set(current_revisions(store)) == set(heads())
    assert pending_changes(store) == []


def test_every_head_descends_from_the_foundation():
    # Slices land as siblings of the foundation for now; they are relinked into one line at
    # integration, and this becomes a single-head assertion then.
    for head in heads():
        assert FOUNDATION_REVISION in revision_lineage(head)


def _revision(store, body) -> None:
    """Run `body(op)` the way a revision's upgrade() runs, on the store's own connection."""
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    from immich_memories.db.migrate import migration_options

    with store.begin() as connection:
        context = MigrationContext.configure(connection, opts=migration_options(store.schema))
        with Operations.context(context) as operations:
            body(operations)


def test_a_table_rebuild_finds_the_table_in_the_real_schema(store):
    # SQLite cannot ALTER most things, so batch mode copies the table and renames the copy.
    # Alembic renders that rename with the schema it is given, past the translate map, which
    # is why revisions name migration_schema() and never the symbolic one.
    from immich_memories.db import migration_schema

    def add_note(operations) -> None:
        assert migration_schema() == store.schema
        with operations.batch_alter_table(
            "store_meta", schema=migration_schema(), recreate="always"
        ) as batch:
            batch.add_column(sa.Column("note", sa.Text(), nullable=True))

    _revision(store, add_note)

    with store.connect() as connection:
        columns = sa.inspect(connection).get_columns("store_meta", schema=store.schema)
    assert "note" in {column["name"] for column in columns}


def test_a_populated_store_rolls_back_revision_by_revision_and_up_again(store, tmp_path):
    """Each downgrade drops the tables its revision created, with their rows, and nothing else.

    Every table that survives a step keeps its rows exactly; going back up rebuilds the
    dropped tables empty. This is the rollback contract docs/designs/2026-09-27-the-store.md
    states.
    """
    from immich_memories.config_loader import Config, set_config
    from immich_memories.db import upgrade
    from immich_memories.db.inventory import digests, table_digest

    from .legacy_home import fill_every_table, write_legacy_home

    config = Config()
    config.cache.database = "~/.immich-memories/cache.db"
    config.cache.directory = "~/.immich-memories/cache"
    set_config(config)
    try:
        fill_every_table(store, write_legacy_home(tmp_path / "home"))
    finally:
        set_config(None)
    with store.connect() as connection:
        before = digests(connection)
    (head,) = heads()
    remaining = set(before)

    for target in [*revision_lineage(head)[1:], "base"]:
        downgrade(store, target)
        surviving = _tables(store) & set(before)
        with store.connect() as connection:
            kept = {name: table_digest(connection, _table(name)) for name in surviving}

        assert surviving < remaining
        assert kept == {name: before[name] for name in surviving}
        remaining = surviving

    assert remaining == set()
    upgrade(store)
    with store.connect() as connection:
        assert all(rows == 0 for rows, _ in digests(connection).values())


def _table(name: str) -> sa.Table:
    return next(table for table in metadata.sorted_tables if table.name == name)


def test_no_store_column_declares_a_length():
    # SQLite ignores VARCHAR(n), so a length is a constraint only PostgreSQL enforces and no
    # SQLite test can catch; PostgreSQL stores unbounded varchar exactly as fast.
    bounded = [
        f"{table.name}.{column.name}"
        for table in metadata.sorted_tables
        for column in table.columns
        if isinstance(column.type, sa.String) and column.type.length is not None
    ]

    assert bounded == []
