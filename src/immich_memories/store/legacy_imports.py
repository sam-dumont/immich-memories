"""The legacy import: every domain's importer in dependency order, resumable and recorded.

Each importer is idempotent and reads its files read-only, so an interrupted import is
finished by running it again. What makes the rerun cheap is the record each importer leaves
in `store_meta` once it completes: the path, size, mtime and SHA-256 of every file it read.
An importer whose files still match its record is skipped. When all of them have run, one
more record (`IMPORT_RECORD`) marks the whole import done.

The same import runs by itself the first time a process opens a store that has no such
record while legacy files exist (`enable_first_open_import`). That hook is registered by the
app's entry points, after the config has loaded, and runs outside the migration lock: later
processes pay one indexed read of `store_meta` and nothing else.
"""

from __future__ import annotations

import hashlib
import importlib
import logging
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from immich_memories.db import Store, iso_from_db, now_db
from immich_memories.db.leases import Lease
from immich_memories.db.legacy_import import (
    IMPORT_RECORD,
    ImportOutcome,
    importer_record_key,
    read_import_record,
    write_import_record,
)
from immich_memories.db.store import on_first_open

logger = logging.getLogger(__name__)

IMPORT_FROM_ENV = "IMMICH_MEMORIES_IMPORT_FROM"
_HASH_CHUNK = 1 << 20


@dataclass(frozen=True)
class LegacyImporter:
    """One domain's importer module.

    The module provides `import_legacy(store, home) -> ImportOutcome` and
    `legacy_sources(home) -> list[Path]` (the files it would read), and may provide
    `verify_legacy(store, home) -> list[str]` (every legacy record the store does not hold
    with equal values).
    """

    name: str
    module: str

    def load(self) -> ModuleType:
        return importlib.import_module(self.module)


# Dependency order: people first, since annotations and runs name people.
IMPORTERS: tuple[LegacyImporter, ...] = (
    LegacyImporter("people", "immich_memories.people.transfer"),
    LegacyImporter("annotations", "immich_memories.store.legacy_annotations"),
    LegacyImporter("operations", "immich_memories.operations.store_import"),
)


def legacy_home() -> Path:
    """Where the legacy files are: `IMMICH_MEMORIES_IMPORT_FROM`, then `database.import_from`,
    then `~/.immich-memories`."""
    from immich_memories.config_loader import get_config

    configured = os.environ.get(IMPORT_FROM_ENV) or get_config().database.import_from
    return Path(configured).expanduser() if configured else Path.home() / ".immich-memories"


def fingerprint(path: Path) -> dict[str, Any]:
    """Path, size, mtime (ns) and SHA-256 of one legacy file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK):
            digest.update(chunk)
    stat = path.stat()
    return {
        "path": str(path),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": digest.hexdigest(),
    }


def run_import(
    store: Store, home: Path, report: Callable[[ImportOutcome], None] | None = None
) -> list[ImportOutcome]:
    """Run every importer against `home`, skip those whose files match their record.

    Each completed importer is recorded before the next starts, so an interrupted run
    resumes where it stopped. `report` sees each outcome as it happens.
    """
    home = Path(home).expanduser()
    outcomes: list[ImportOutcome] = []
    for importer in IMPORTERS:
        outcome = _run_one(store, home, importer)
        outcomes.append(outcome)
        if report is not None:
            report(outcome)
    summary = {
        "home": str(home),
        "completed_at": iso_from_db(now_db()),
        "importers": {
            importer.name: {"imported": outcome.imported, "skipped": outcome.skipped}
            for importer, outcome in zip(IMPORTERS, outcomes, strict=True)
        },
    }
    with store.begin() as connection:
        write_import_record(connection, IMPORT_RECORD, summary)
    return outcomes


def _run_one(store: Store, home: Path, importer: LegacyImporter) -> ImportOutcome:
    module = importer.load()
    sources = [fingerprint(path) for path in module.legacy_sources(home)]
    key = importer_record_key(importer.name)
    with store.connect() as connection:
        done = read_import_record(connection, key)
    if done is not None and done.get("home") == str(home) and done.get("sources") == sources:
        note = f"unchanged since the import of {done.get('completed_at')}"
        return ImportOutcome(importer.name, 0, 0, (note,))
    outcome: ImportOutcome = module.import_legacy(store, home)
    record = {
        "home": str(home),
        "sources": sources,
        "completed_at": iso_from_db(now_db()),
        "imported": outcome.imported,
        "skipped": outcome.skipped,
    }
    with store.begin() as connection:
        write_import_record(connection, key, record)
    return outcome


def verify_import(store: Store, home: Path) -> dict[str, list[str]]:
    """Per importer, every legacy record the store lacks or holds with other values."""
    home = Path(home).expanduser()
    problems: dict[str, list[str]] = {}
    for importer in IMPORTERS:
        module = importer.load()
        if not hasattr(module, "verify_legacy"):
            problems[importer.name] = [f"{importer.name} has no verifier"]
            continue
        problems[importer.name] = list(module.verify_legacy(store, home))
    return problems


def has_legacy_files(home: Path) -> bool:
    """Whether any importer finds a file to read under `home`."""
    return any(importer.load().legacy_sources(home) for importer in IMPORTERS)


def import_on_first_open(store: Store) -> None:
    """Import the legacy files once, when the store has no import record and files exist.

    Two processes starting together queue on a lease; the second finds the record the first
    wrote. A failure is logged and leaves no record, so the next start tries again.
    """
    try:
        if _recorded(store):
            return
        home = legacy_home()
        if not has_legacy_files(home):
            return
        lease = _import_lease(store)
        lease.acquire(wait=True)
        try:
            if not _recorded(store):
                logger.info(
                    "Importing the legacy files under %s into %s (once)", home, store.location
                )
                run_import(store, home, report=_log_outcome)
        finally:
            lease.release()
    except Exception:  # WHY: the app must still start; the import retries on the next start
        logger.exception(
            "The legacy import failed; it runs again at the next start, "
            "or by hand with `immich-memories store import`"
        )


def enable_first_open_import() -> None:
    """Have every store this process opens import the legacy files the first time."""
    on_first_open(import_on_first_open)


def _log_outcome(outcome: ImportOutcome) -> None:
    logger.info(
        "  %s: %d imported, %d already there", outcome.source, outcome.imported, outcome.skipped
    )


def _recorded(store: Store) -> bool:
    with store.connect() as connection:
        return read_import_record(connection) is not None


def _import_lease(store: Store) -> Lease:
    path = store.location.sqlite_path
    lock = (
        path.with_name(path.name + ".import.lock")
        if path is not None
        else Path(tempfile.gettempdir()) / "immich-memories-import.lock"
    )
    return Lease("legacy-import", lock, store)
