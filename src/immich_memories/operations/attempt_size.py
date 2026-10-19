"""An attempt folder's size, recorded once so the budget does not walk every folder each time."""

from __future__ import annotations

import json
import os
from pathlib import Path

from immich_memories.security import write_secret_file

ATTEMPT_SIZE = "size.private.json"
_STATUS = "status.private.json"


def walk_size(directory: Path) -> int:
    """Total bytes under `directory`, by walking it."""
    size = 0
    for current, _dirs, files in os.walk(directory):
        for name in files:
            try:
                size += (Path(current) / name).lstat().st_size
            except OSError:
                continue
    return size


def record_attempt_size(directory: Path) -> int | None:
    """Walk the attempt once and note its size against the status file it was measured at.

    Called when an attempt finishes, so later budget passes read a few bytes instead of
    walking the frames, plans and records inside. Returns None when the attempt has no status.
    """
    try:
        stamp = (directory / _STATUS).stat().st_mtime_ns
    except OSError:
        return None
    size = walk_size(directory)
    try:
        write_secret_file(
            directory / ATTEMPT_SIZE, json.dumps({"size": size, "status_mtime_ns": stamp})
        )
    except OSError:
        return size
    return size


def recorded_attempt_size(directory: Path) -> int | None:
    """The size noted at finish, or None when it is missing or the status changed since."""
    try:
        note = json.loads((directory / ATTEMPT_SIZE).read_text())
        stamp = (directory / _STATUS).stat().st_mtime_ns
        return int(note["size"]) if note["status_mtime_ns"] == stamp else None
    except (OSError, ValueError, KeyError, TypeError):
        return None
