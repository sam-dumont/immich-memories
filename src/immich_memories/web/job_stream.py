"""What one tick of a job's event stream does: look at the files, build the view only if needed."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from immich_memories.operations.cut_progress import PROGRESS_FILE
from immich_memories.operations.editorial_attempt import LATEST_ATTEMPT
from immich_memories.web.jobs import JobRunner
from immich_memories.web.schemas import Job

# A liveness probe is reused for this many seconds; the stream notices a dead child that late.
LEASE_TTL = 5.0


@dataclass(frozen=True)
class Seen:
    """What the stream last looked at (`stamp`) and sent (`view`)."""

    stamp: Any
    view: str


def _stamp(path: Path | None) -> tuple[int, int] | None:
    try:
        stat = path.stat() if path is not None else None
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size) if stat else None


def watched_stamps(runner: JobRunner, job: Job, cut_root: Path | None) -> tuple[Any, ...]:
    """Modification stamps of the files a job's view is built from, to skip an unchanged one."""
    progress_file = job.meta.get("progress_file")
    stamps: list[Any] = [
        _stamp(runner.log_path(job.id)),
        _stamp(Path(str(progress_file)) if progress_file else None),
    ]
    if job.kind == "cut":
        pointer = cut_root / LATEST_ATTEMPT if cut_root is not None else None
        stamps.append(_stamp(pointer))
        try:
            directory = Path(json.loads(pointer.read_text())["directory"]) if pointer else None
        except (OSError, ValueError, KeyError, TypeError):
            directory = None
        stamps += [
            _stamp(directory / name if directory else None)
            for name in ("status.private.json", PROGRESS_FILE)
        ]
    return tuple(stamps)


def next_event(
    runner: JobRunner,
    job: Job,
    cut_root: Path | None,
    build: Callable[[Job], str],
    seen: Seen,
) -> tuple[Seen, str | None, bool]:
    """One stream tick: the view when something it is built from changed, else None.

    The files a view reads are stat-ed first; an unchanged set skips the parse of the attempt
    record and the lease probe. A probe is reused for `LEASE_TTL` seconds, and the tick after
    that re-reads once even when no file moved, so a child that died is still noticed.
    Returns the new `Seen`, the view to send (if any) and whether the job still runs.
    """
    running = job.status == "running"
    stamp = (job, watched_stamps(runner, job, cut_root), int(time.monotonic() // LEASE_TTL))
    if stamp == seen.stamp:
        return seen, None, running
    view = build(job)
    return Seen(stamp, view), (view if view != seen.view else None), running
