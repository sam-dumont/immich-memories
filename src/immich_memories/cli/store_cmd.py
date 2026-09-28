"""The store: its state, the legacy import, copies, backups and restores."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import click

from immich_memories.cli._helpers import console, print_error, print_success
from immich_memories.db import StoreLocation, open_store, resolve_location


def register_store_commands(cli_group: click.Group) -> None:
    """Register the `store` group on the main CLI group."""

    @cli_group.group()
    def store() -> None:
        """The database that holds your decisions, model answers, run history and settings.

        SQLite at ~/.immich-memories/store.db unless IMMICH_MEMORIES_DATABASE_URL (or
        `database.url`) names another one. Stop the app before `restore`.
        """

    _register_status(store)
    _register_import(store)
    _register_copy(store)
    _register_backup(store)
    _register_restore(store)


def _location(ctx: click.Context) -> StoreLocation:
    return resolve_location(ctx.obj["config"])


def _register_status(group: click.Group) -> None:
    @group.command()
    @click.pass_context
    def status(ctx: click.Context) -> None:
        """Backend, URL, schema, revision, import record, row counts and size."""
        from immich_memories.db.status import store_status

        _print_status(store_status(_location(ctx)))


def _print_status(state: Any) -> None:
    from immich_memories.db.migrate import heads

    console.print(f"Backend:   {state.backend}")
    console.print(f"URL:       {state.url}")
    if state.schema:
        console.print(f"Schema:    {state.schema}")
    if state.network_filesystem:
        console.print(
            f"[yellow]Warning: the SQLite file is on a network filesystem "
            f"({state.network_filesystem}); keep it on a local disk or use PostgreSQL.[/yellow]"
        )
    if not state.exists:
        console.print("The store has not been created yet; the app creates it on first use.")
        return
    head = "at head" if state.at_head else f"not at head ({', '.join(heads())})"
    console.print(f"Revision:  {', '.join(state.revisions) or 'none'} ({head})")
    record = state.import_record
    imported = (
        f"from {record.get('home')} at {record.get('completed_at')}" if record else "not recorded"
    )
    console.print(f"Import:    {imported}")
    if state.size_bytes is not None:
        console.print(f"Size:      {state.size_bytes / 1_048_576:.1f} MiB")
    for name, count in sorted(state.counts.items()):
        console.print(f"  {name:<32} {count:>10}")


def _register_import(group: click.Group) -> None:
    @group.command(name="import")
    @click.option(
        "--from",
        "source",
        type=click.Path(file_okay=False, path_type=Path),
        default=None,
        help="The directory holding the legacy files (default: IMMICH_MEMORIES_IMPORT_FROM, "
        "then database.import_from, then ~/.immich-memories). They are only read, never changed",
    )
    @click.option(
        "--verify",
        is_flag=True,
        help="Afterwards, check that every legacy record is in the store with equal values; "
        "exit 1 on any difference",
    )
    @click.pass_context
    def import_(ctx: click.Context, source: Path | None, verify: bool) -> None:
        """Bring the files the app used before the store into it.

        Safe to run again: a record the store holds is never replaced, and an importer
        whose files have not changed since it last completed is skipped. An interrupted
        import finishes where it stopped.
        """
        from immich_memories.store.legacy_imports import legacy_home, run_import, verify_import

        home = source or legacy_home()
        store = open_store(location=_location(ctx))
        console.print(f"Importing from {home} into {store.location}")
        run_import(store, home, report=_print_outcome)
        if not verify:
            return
        if not _print_verification(verify_import(store, home)):
            sys.exit(1)
        print_success("Every legacy record is in the store")


def _print_verification(problems: dict[str, list[str]], shown: int = 50) -> bool:
    """Print each domain's differences; True when there are none."""
    for name, lines in problems.items():
        if not lines:
            console.print(f"  {name}: verified")
            continue
        console.print(f"  [red]{name}: {len(lines)} differences[/red]")
        for line in lines[:shown]:
            console.print(f"    {line}")
        if len(lines) > shown:
            console.print(f"    ... and {len(lines) - shown} more")
    return not any(problems.values())


def _print_outcome(outcome: Any) -> None:
    console.print(
        f"  {outcome.source}: {outcome.imported} imported, {outcome.skipped} already there"
    )
    for note in outcome.notes:
        console.print(f"    {note}")


def _register_copy(group: click.Group) -> None:
    @group.command()
    @click.option("--to", "target_url", required=True, help="The database URL to copy into")
    @click.option(
        "--schema",
        default=None,
        help="The PostgreSQL schema to copy into (default: the configured one)",
    )
    @click.option("--force", is_flag=True, help="Empty a target that already holds rows")
    @click.pass_context
    def copy(ctx: click.Context, target_url: str, schema: str | None, force: bool) -> None:
        """Copy every table into another store: SQLite to PostgreSQL, or back.

        The target is migrated first, and every table's row count and content digest are
        compared afterwards. Point IMMICH_MEMORIES_DATABASE_URL at the target to switch.
        """
        from immich_memories.db.bootstrap import normalize_url
        from immich_memories.db.copy import TargetNotEmptyError, copy_store

        location = _location(ctx)
        try:
            target = StoreLocation(url=normalize_url(target_url), schema=schema or location.schema)
        except ValueError as error:
            print_error(str(error))
            sys.exit(1)
        source_store = open_store(location=location)
        target_store = open_store(location=target)
        if (source_store.location.url, source_store.schema) == (target.url, target_store.schema):
            print_error("the target is the store itself")
            sys.exit(1)
        try:
            report = copy_store(source_store, target_store, force=force)
        except TargetNotEmptyError as error:
            print_error(f"{error}. Pass --force to replace them.")
            sys.exit(1)
        for name, count in report.copied.items():
            console.print(f"  {name:<32} {count:>10}")
        if report.mismatched:
            print_error(f"the copy differs from the source in: {', '.join(report.mismatched)}")
            sys.exit(1)
        print_success(
            f"Copied {sum(report.copied.values())} rows into {target}; every table matches"
        )


def _register_backup(group: click.Group) -> None:
    @group.command()
    @click.option(
        "--to",
        "destination",
        type=click.Path(dir_okay=False, path_type=Path),
        default=None,
        help="The backup file (default: ~/.immich-memories/backups/store-UTCTIME.db, "
        ".dump on PostgreSQL)",
    )
    @click.pass_context
    def backup(ctx: click.Context, destination: Path | None) -> None:
        """Write a consistent backup while the app runs, with a manifest beside it.

        SQLite: VACUUM INTO. PostgreSQL: pg_dump of the schema in custom format, which needs
        the PostgreSQL client tools on PATH.
        """
        from immich_memories.db.backup import BackupError, backup_store, manifest_path
        from immich_memories.db.store import unmigrated_store

        location = _location(ctx)
        destination = destination or _default_backup(location)
        store = unmigrated_store(location)
        try:
            manifest = backup_store(store, destination)
        except BackupError as error:
            print_error(str(error))
            sys.exit(1)
        finally:
            store.engine.dispose()
        rows = sum(manifest.counts.values())
        print_success(f"Backed up {rows} rows to {destination}")
        console.print(f"Manifest: {manifest_path(destination)}")


def _default_backup(location: StoreLocation) -> Path:
    from datetime import UTC, datetime

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    suffix = "db" if location.dialect_name == "sqlite" else "dump"
    return Path.home() / ".immich-memories" / "backups" / f"store-{stamp}.{suffix}"


def _register_restore(group: click.Group) -> None:
    @group.command()
    @click.option(
        "--from",
        "backup_file",
        required=True,
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
        help="A file `store backup` wrote; its manifest must sit beside it",
    )
    @click.option("--force", is_flag=True, help="Replace a store that already holds rows")
    @click.pass_context
    def restore(ctx: click.Context, backup_file: Path, force: bool) -> None:
        """Replace the store with a backup, migrate it to head and check its row counts.

        Stop the app first: a restore cannot reach another process's connections.
        """
        from immich_memories.db.backup import BackupError, restore_store

        try:
            manifest = restore_store(_location(ctx), backup_file, force=force)
        except BackupError as error:
            print_error(str(error))
            sys.exit(1)
        print_success(
            f"Restored {sum(manifest.counts.values())} rows from {backup_file} "
            f"(taken {manifest.created_at} by {manifest.app_version})"
        )
