"""When this process began, read before any heavy import (#1429)."""

import time

_unclaimed = [time.perf_counter()]


def claim() -> float | None:
    """The process start, handed to the first run that owns this process and to no later one."""
    return _unclaimed.pop() if _unclaimed else None
