"""Log a generation child's phase progress, so a long scheduled run is not silent."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)

# Under half the heartbeat, so a beat reaches the log within the minute it is due.
_POLL_SECONDS = 15.0


@contextmanager
def log_phase_progress(
    read_events: Callable[[], list[dict[str, Any]]],
    interval_seconds: float = _POLL_SECONDS,
) -> Iterator[None]:
    """Log each phase event the child persists while the block runs.

    The child's own output is captured for the attempt record, so `kubectl logs` shows
    nothing for the hour a year review takes unless the parent reports what the child
    wrote to the store.
    """
    logged = 0
    stop = threading.Event()

    def drain() -> None:
        nonlocal logged
        try:
            events = read_events()
        except Exception:  # WHY: progress lines must never fail a run
            logger.debug("Could not read phase progress", exc_info=True)
            return
        for event in events[logged:]:
            total = f"{event['current']}/{event['total']} " if event.get("total") else ""
            logger.info(
                "Phase %s: %s%s (%.0fs)",
                event.get("label", event.get("phase")),
                total,
                event.get("message", ""),
                event.get("elapsed_seconds", 0.0),
            )
        logged = len(events)

    def poll() -> None:
        while not stop.wait(interval_seconds):
            drain()

    thread = threading.Thread(target=poll, name="phase-log", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=5)
        drain()
