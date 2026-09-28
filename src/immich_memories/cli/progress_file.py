"""A JSON progress file a long command keeps for a watcher, such as the web client's job page."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path


def write_progress(path: Path | None, record: dict) -> None:
    """Replace the file with this record, whole: a reader never sees half of one."""
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(record | {"updated_at": time.time()}))
    os.replace(temporary, path)


def progress_writer(path: Path | None):
    # Imported once, as the command starts: a timing module that cannot load fails the render
    # before any work, never inside the engine's first progress report.
    from immich_memories.tracking.timing import active

    def report(phase: str, fraction: float, message: str) -> None:
        collected = active()
        estimate = collected.diagnostics.get("progress", {}) if collected else {}
        write_progress(
            path,
            {"done": False, "phase": phase, "fraction": fraction, "message": message, **estimate},
        )

    return report if path is not None else None
