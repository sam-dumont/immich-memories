"""When this process began, and where its cold start went, read before any heavy import (#1429)."""

import time
from dataclasses import dataclass, field

# A process that never claims its start (the web server) must not grow this without end.
_MAX_MARKS = 16


@dataclass
class Startup:
    started: float
    marks: list[tuple[str, float]] = field(default_factory=list)


_process = Startup(time.perf_counter())
_unclaimed = [_process]


def mark(phase: str) -> None:
    """Record that a startup phase ended now.

    Marks keep landing after a run claims the start: the system probe runs between the
    claim and the root span opening. The run reads only the marks before its root opened.
    """
    if len(_process.marks) < _MAX_MARKS:
        _process.marks.append((phase, time.perf_counter()))


def claim() -> Startup | None:
    """The process start, handed to the first run that owns this process and to no later one."""
    return _unclaimed.pop() if _unclaimed else None
