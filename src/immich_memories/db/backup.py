"""Back up and restore the store, with a manifest that says what the backup holds.

SQLite: `VACUUM INTO` writes a consistent copy while the app keeps running, and a restore
swaps the file in with every engine of this process disposed. PostgreSQL: `pg_dump` of our
schema in custom format, taken on a snapshot the manifest's row counts were read from, and
`pg_restore` back into the configured schema. Either way the restored store is migrated to
head and its row counts are checked against the manifest.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Connection, make_url

from immich_memories.db.bootstrap import StoreLocation
from immich_memories.db.inventory import (
    present_counts,
    recorded_revisions,
    row_counts,
    store_tables,
)
from immich_memories.db.migrate import VERSION_TABLE, current_revisions
from immich_memories.db.sqlite_files import private_database_path
from immich_memories.db.store import Store, close_stores, open_store, unmigrated_store
from immich_memories.db.time import iso_from_db, now_db

MANIFEST_SUFFIX = ".manifest.json"
# A pg_restore newer than the server opens each session with settings the server lacks
# (17 added `SET transaction_timeout`). That error is harmless; the manifest's row counts,
# checked after every restore, catch anything that is not.
_NEWER_CLIENT_SETTING = "unrecognized configuration parameter"


class BackupError(RuntimeError):
    """A backup or restore that could not be done, with the reason in words."""


@dataclass(frozen=True)
class Manifest:
    """What a backup file holds; written as JSON beside it."""

    app_version: str
    revisions: list[str]
    backend: str
    schema: str | None
    counts: dict[str, int]
    created_at: str

    def write(self, backup: Path) -> Path:
        path = manifest_path(backup)
        path.write_text(json.dumps(asdict(self), indent=2, sort_keys=True) + "\n")
        path.chmod(0o600)
        return path


def manifest_path(backup: Path) -> Path:
    """Where the manifest of `backup` sits: beside it, named after it."""
    return backup.with_name(backup.name + MANIFEST_SUFFIX)


def read_manifest(backup: Path) -> Manifest:
    """The manifest beside `backup`; BackupError when it is missing or unreadable."""
    path = manifest_path(backup)
    try:
        return Manifest(**json.loads(path.read_text()))
    except (OSError, ValueError, TypeError) as error:
        raise BackupError(f"no readable manifest at {path}: {error}") from None


def backup_store(store: Store, destination: Path) -> Manifest:
    """Write a consistent backup of `store` to `destination`, and its manifest beside it."""
    destination = Path(destination).expanduser()
    if destination.exists():
        raise BackupError(f"{destination} already exists; name a new file")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if store.dialect_name == "sqlite":
        manifest = _backup_sqlite(store, destination)
    else:
        manifest = _backup_postgresql(store, destination)
    manifest.write(destination)
    return manifest


def _manifest(store: Store, revisions: tuple[str, ...], counts: dict[str, int]) -> Manifest:
    from immich_memories import __version__

    return Manifest(
        app_version=__version__,
        revisions=list(revisions),
        backend=store.dialect_name,
        schema=store.schema,
        counts=counts,
        created_at=iso_from_db(now_db()) or "",
    )


def _backup_sqlite(store: Store, destination: Path) -> Manifest:
    private_database_path(destination)
    raw = store.engine.raw_connection()
    try:
        # The driver connection runs in autocommit, which VACUUM needs.
        raw.driver_connection.execute("VACUUM INTO ?", (str(destination),))  # type: ignore[union-attr]
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    finally:
        raw.close()
    copy = unmigrated_store(StoreLocation(url=f"sqlite:///{destination}"))
    try:
        with copy.connect() as connection:
            counts = present_counts(connection, None)
        return _manifest(store, current_revisions(copy), counts)
    finally:
        copy.engine.dispose()


def _backup_postgresql(store: Store, destination: Path) -> Manifest:
    pg_dump = _tool("pg_dump")
    with store.connect() as connection:
        # The counts and the dump read one snapshot, so the manifest describes the file exactly.
        connection.execute(sa.text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
        snapshot: str = connection.execute(sa.text("SELECT pg_export_snapshot()")).scalar_one()
        counts = present_counts(connection, store.schema)
        revisions = recorded_revisions(connection, store.schema)
        _run(
            [
                pg_dump,
                "--format=custom",
                f"--schema={store.schema}",
                f"--snapshot={snapshot}",
                f"--file={destination}",
                _libpq_uri(store.location),
            ],
            store.location,
        )
        connection.rollback()
    destination.chmod(0o600)
    return _manifest(store, revisions, counts)


def restore_store(location: StoreLocation, backup: Path, *, force: bool = False) -> Manifest:
    """Replace the store at `location` with `backup`, migrate it to head, check the counts.

    A store holding any row is only replaced with `force`. Stop every other process using
    the store first: this one disposes its own engines, it cannot reach theirs.
    """
    backup = Path(backup).expanduser()
    manifest = read_manifest(backup)
    if not backup.is_file():
        raise BackupError(f"{backup} does not exist")
    if manifest.backend != location.dialect_name:
        raise BackupError(
            f"the backup is {manifest.backend} and the store is {location.dialect_name}; "
            "restore it into a store of its own backend, then use `store copy`"
        )
    held = _rows_held(location)
    if held and not force:
        raise BackupError(f"the store already holds {held} rows; pass --force to replace them")
    close_stores()
    if location.dialect_name == "sqlite":
        _swap_sqlite(location, backup)
    else:
        _restore_postgresql(location, backup, manifest)
    store = open_store(location=location)
    with store.connect() as connection:
        now = row_counts(connection)
    wrong = {name: (count, now.get(name)) for name, count in manifest.counts.items()}
    wrong = {name: pair for name, pair in wrong.items() if pair[0] != pair[1]}
    if wrong:
        listing = ", ".join(
            f"{n}: {want} expected, {got} found" for n, (want, got) in wrong.items()
        )
        raise BackupError(f"the restored store does not match its manifest: {listing}")
    return manifest


def _rows_held(location: StoreLocation) -> int:
    path = location.sqlite_path
    if location.dialect_name == "sqlite" and (path is None or not path.exists()):
        return 0
    store = unmigrated_store(location)
    try:
        with store.connect() as connection:
            if location.dialect_name == "postgresql":
                _refuse_foreign_tables(connection, location.schema)
            return sum(present_counts(connection, store.schema).values())
    finally:
        store.engine.dispose()


def _refuse_foreign_tables(connection: Connection, schema: str) -> None:
    ours = {table.name for table in store_tables()} | {VERSION_TABLE}
    foreign = set(sa.inspect(connection).get_table_names(schema=schema)) - ours
    if foreign:
        raise BackupError(
            f"schema {schema!r} holds tables that are not the store's ({', '.join(sorted(foreign))}); "
            "a restore replaces the whole schema, so give the store a schema of its own"
        )


def _swap_sqlite(location: StoreLocation, backup: Path) -> None:
    target = location.sqlite_path
    if target is None:
        raise BackupError("an in-memory store cannot be restored")
    private_database_path(target)
    staged = target.with_name(target.name + ".restoring")
    shutil.copyfile(backup, staged)
    staged.chmod(0o600)
    # A WAL left beside the old file would be replayed into the new one.
    for suffix in ("-wal", "-shm", "-journal"):
        with suppress(FileNotFoundError):
            Path(str(target) + suffix).unlink()
    os.replace(staged, target)


def _restore_postgresql(location: StoreLocation, backup: Path, manifest: Manifest) -> None:
    pg_restore = _tool("pg_restore")
    source_schema = manifest.schema or location.schema
    engine = sa.create_engine(location.sa_url)
    try:
        with engine.begin() as connection:
            inspector = sa.inspect(connection)
            if source_schema != location.schema and inspector.has_schema(source_schema):
                raise BackupError(
                    f"the backup's schema {source_schema!r} exists in this database; a restore "
                    f"into {location.schema!r} needs it free for the moment it takes"
                )
            connection.execute(sa.schema.DropSchema(location.schema, cascade=True, if_exists=True))
        _run(
            [
                pg_restore,
                "--no-owner",
                "--no-acl",
                f"--dbname={_libpq_uri(location)}",
                str(backup),
            ],
            location,
            tolerated=_NEWER_CLIENT_SETTING,
        )
        if source_schema != location.schema:
            with engine.begin() as connection:
                preparer = connection.dialect.identifier_preparer
                # DDL takes no bound identifiers: both names go through the dialect's quoting.
                connection.execute(
                    sa.text(  # nosemgrep: avoid-sqlalchemy-text
                        f"ALTER SCHEMA {preparer.quote_schema(source_schema)} "
                        f"RENAME TO {preparer.quote_schema(location.schema)}"
                    )
                )
    finally:
        engine.dispose()


def _tool(name: str) -> str:
    found = shutil.which(name)
    if found is None:
        raise BackupError(
            f"{name} was not found on PATH. Install the PostgreSQL client tools "
            "(Debian/Ubuntu: postgresql-client), at least as new as the server; "
            "the Docker image ships them."
        )
    return found


def _libpq_uri(location: StoreLocation) -> str:
    """The server address as libpq reads it; the password travels in PGPASSWORD instead."""
    url = make_url(location.url).set(drivername="postgresql", password=None)
    return url.render_as_string(hide_password=False)


def _run(command: list[str], location: StoreLocation, tolerated: str | None = None) -> None:
    """Run a client tool; an exit whose only errors mention `tolerated` counts as success."""
    env: dict[str, Any] = os.environ.copy()
    password = make_url(location.url).password
    if password is not None:
        env["PGPASSWORD"] = str(password)
    result = subprocess.run(command, env=env, capture_output=True, text=True, check=False)  # noqa: S603
    if result.returncode == 0:
        return
    errors = [line for line in result.stderr.splitlines() if "ERROR:" in line]
    if tolerated is not None and errors and all(tolerated in line for line in errors):
        return
    tool = Path(command[0]).name
    raise BackupError(f"{tool} failed: {result.stderr.strip() or result.returncode}")
