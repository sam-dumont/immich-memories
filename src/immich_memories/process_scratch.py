"""Each process's own scratch folder, and the sweep that clears the ones dead processes left.

Temporary files are removed when their work finishes, but a run killed mid-batch (an OOM kill,
a pod restart, SIGKILL) finishes nothing: one install kept a 5.4 GB folder of detector frames
for days after the run that wrote it died. Nothing on disk said whose it was, so nothing could
safely remove it while another run might still be using it.

So every process that takes the scratch (`runtime_scratch`) works inside a folder of its own and
holds an exclusive `flock` on a file in it for as long as it lives. The operating system drops
that lock when the process dies, however it dies, so a folder whose lock can be taken belongs to
nobody. A reused PID cannot fake ownership the way a PID file can.

A folder is only swept an hour after it last changed: a process that has just ended may have
handed a file to the one that started it. Scratch written before folders had owners has no lock
to ask, so it goes once it is a day old.
"""

from __future__ import annotations

import contextlib
import fcntl
import logging
import os
import shutil
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

logger = logging.getLogger(__name__)

OWNED_PREFIX = "proc-"
_LOCK = ".owner.lock"
_OWNED_GRACE_SECONDS = 3600
_UNOWNED_GRACE_SECONDS = 24 * 3600
# Detector frames were written straight into the cache directory before they moved into
# the process's own scratch; a killed run's folders there have no owner either.
_LEGACY_CACHE_SCRATCH = "immich-detector-frames-*"
_active: list[Path] = []


def active_scratch() -> Path | None:
    """This process's own scratch folder, or None outside `runtime_scratch`."""
    return _active[-1] if _active else None


@contextlib.contextmanager
def owned_scratch(scratch: Path) -> Iterator[Path]:
    """A private folder inside `scratch` that this process owns until the block ends."""
    folder = Path(tempfile.mkdtemp(prefix=OWNED_PREFIX, dir=scratch))
    descriptor = os.open(folder / _LOCK, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        _active.append(folder)
        try:
            yield folder
        finally:
            _active.remove(folder)
    finally:
        os.close(descriptor)


def sweep_stale_scratch(scratch: Path, cache: Path) -> int:
    """Remove scratch no live process owns; returns how many folders and files went."""
    now = time.time()
    removed = 0
    for entry in _children(scratch):
        if entry.name.startswith(OWNED_PREFIX) and entry.is_dir() and not entry.is_symlink():
            removed += _remove_unowned(entry, now)
        elif _older_than(entry, now, _UNOWNED_GRACE_SECONDS):
            removed += _remove(entry)
    for entry in cache.glob(_LEGACY_CACHE_SCRATCH):
        if entry.is_dir() and _older_than(entry, now, _UNOWNED_GRACE_SECONDS):
            removed += _remove(entry)
    if removed:
        logger.info("Removed %d scratch folders and files left by runs that ended", removed)
    return removed


def _children(directory: Path) -> list[Path]:
    try:
        return list(directory.iterdir())
    except OSError:
        return []


def _older_than(path: Path, now: float, seconds: float) -> bool:
    try:
        return now - path.lstat().st_mtime > seconds
    except OSError:
        return False


def _remove_unowned(folder: Path, now: float) -> int:
    if not _older_than(folder, now, _OWNED_GRACE_SECONDS):
        return 0
    try:
        descriptor = os.open(folder / _LOCK, os.O_RDWR)
    except FileNotFoundError:
        # Between mkdtemp and the lock, or a lock already half swept: no owner to ask.
        return _remove(folder) if _older_than(folder, now, _UNOWNED_GRACE_SECONDS) else 0
    except OSError:
        return 0
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return 0
    else:
        # Held while removing, so an owner cannot appear halfway through.
        return _remove(folder)
    finally:
        os.close(descriptor)


def _remove(entry: Path) -> int:
    try:
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()
    except OSError as error:
        logger.debug("Could not remove leftover scratch: %s", type(error).__name__)
        return 0
    return 1
