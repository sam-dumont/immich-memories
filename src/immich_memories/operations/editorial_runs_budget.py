"""Keep `editorial-runs/` inside `cache.editorial_runs_max_size_gb`, oldest attempts first.

Every cut leaves an attempt folder (its plan, frames and records) and nothing ever removed
one: a single install grew the folder to 10 GB. Most of it is attempts nothing reads again,
the failed, cancelled and superseded ones. The ones a run in the history points at are what
`runs story`, `runs why` and `runs render` read, so they go last, and only when the budget
cannot be met without them.

Never removed, whatever the budget: an attempt a live run still holds, the newest attempt of
each cut key (the web client and the next run of the same request read it), and anything
touched in the last day, so a cut waiting for its render keeps its plan.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import sqlalchemy as sa

from immich_memories.db.tables import pipeline_runs, run_attempts
from immich_memories.operations.editorial_attempt import LATEST_ATTEMPT, read_editorial_attempt

if TYPE_CHECKING:
    from immich_memories.config.loader import Config
    from immich_memories.db import Store

logger = logging.getLogger(__name__)

EDITORIAL_RUNS = "editorial-runs"
_RECENT_SECONDS = 24 * 3600
_GB = 1024**3


@dataclass(frozen=True)
class _Attempt:
    directory: Path
    touched: float
    size: int


@dataclass(frozen=True)
class Pruned:
    """What one pass removed, and how far over the budget what it had to keep still is."""

    removed: tuple[Path, ...]
    freed_bytes: int
    overflow_bytes: int


def keep_editorial_runs_in_budget(config: Config, *, store: Store | None = None) -> Pruned:
    """Prune the configured cache's attempt folders down to the configured budget."""
    from immich_memories.db import open_store

    return prune_editorial_runs(
        config.cache.cache_path / EDITORIAL_RUNS,
        max_bytes=int(config.cache.editorial_runs_max_size_gb * _GB),
        store=store or open_store(config),
    )


def prune_editorial_runs(root: Path, *, max_bytes: int, store: Store) -> Pruned:
    """Remove whole attempt folders, unread ones before the ones a listed run points at."""
    attempts = [_measure(directory) for directory in _attempt_dirs(root)]
    total = sum(attempt.size for attempt in attempts)
    if total <= max_bytes:
        return Pruned((), 0, 0)
    kept = _protected(root, attempts, store)
    referenced = _referenced(store)
    candidates = sorted(
        (attempt for attempt in attempts if attempt.directory not in kept),
        key=lambda attempt: (attempt.directory.resolve() in referenced, attempt.touched),
    )
    removed: list[Path] = []
    freed = 0
    for attempt in candidates:
        if total - freed <= max_bytes:
            break
        shutil.rmtree(attempt.directory, ignore_errors=True)
        if not attempt.directory.exists():
            removed.append(attempt.directory)
            freed += attempt.size
    overflow = max(0, total - freed - max_bytes)
    if removed:
        logger.info(
            "Removed %d old cut attempts (%.1f MB) to keep editorial-runs in its budget",
            len(removed),
            freed / 1_000_000,
        )
    if overflow:
        logger.warning(
            "editorial-runs is %.1f MB over cache.editorial_runs_max_size_gb with only live, "
            "recent and newest attempts left; raise the budget or delete old runs",
            overflow / 1_000_000,
        )
    return Pruned(tuple(removed), freed, overflow)


def _attempt_dirs(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return [
        attempt
        for key in root.iterdir()
        if key.is_dir() and not key.is_symlink()
        for attempt in (key / "attempts").glob("*")
        if attempt.is_dir() and not attempt.is_symlink()
    ]


def _measure(directory: Path) -> _Attempt:
    size = 0
    for current, _dirs, files in os.walk(directory):
        for name in files:
            try:
                size += (Path(current) / name).lstat().st_size
            except OSError:
                continue
    status = directory / "status.private.json"
    try:
        touched = (status if status.exists() else directory).stat().st_mtime
    except OSError:
        touched = time.time()
    return _Attempt(directory, touched, size)


def _protected(root: Path, attempts: list[_Attempt], store: Store) -> set[Path]:
    newest = {pointer for key in root.iterdir() if (pointer := _newest_of(key)) is not None}
    recent = time.time() - _RECENT_SECONDS
    return {
        attempt.directory
        for attempt in attempts
        if attempt.directory in newest or attempt.touched >= recent or _live(attempt, store)
    }


def _newest_of(key: Path) -> Path | None:
    try:
        return Path(json.loads((key / LATEST_ATTEMPT).read_text())["directory"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _live(attempt: _Attempt, store: Store) -> bool:
    try:
        return read_editorial_attempt(attempt.directory, store).get("status") == "running"
    except (OSError, ValueError, KeyError):
        return False


def _referenced(store: Store) -> set[Path]:
    """Attempt folders a run still in the history reads from."""
    query = sa.select(run_attempts.c.attempt_dir).where(
        run_attempts.c.run_id.in_(sa.select(pipeline_runs.c.run_id))
    )
    with store.connect() as conn:
        return {Path(row).resolve() for row in conn.execute(query).scalars()}
