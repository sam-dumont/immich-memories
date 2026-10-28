"""Log a generation child's phase progress, so a long scheduled run is not silent."""

from __future__ import annotations

import contextvars
import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# Poll promptly while keeping store reads bounded during long renders.
_POLL_SECONDS = 5.0


@contextmanager
def log_phase_progress(
    read_events: Callable[[int], list[tuple[int, dict[str, Any]]]],
    interval_seconds: float = _POLL_SECONDS,
) -> Iterator[None]:
    """Log each phase event the child persists while the block runs.

    `read_events(after)` returns the events with an id past `after` as `(id, event)`, so a
    poll reads what is new instead of the child's whole log.

    The child's own output is captured for the attempt record, so `kubectl logs` shows
    nothing for the hour a year review takes unless the parent reports what the child
    wrote to the store.
    """
    last_id = 0
    stop = threading.Event()

    def drain() -> None:
        nonlocal last_id
        try:
            events = read_events(last_id)
        except Exception:  # WHY: progress lines must never fail a run
            logger.debug("Could not read phase progress", exc_info=True)
            return
        for event_id, event in events:
            _log_event(event)
            last_id = event_id

    def poll() -> None:
        while not stop.wait(interval_seconds):
            drain()

    # In this block's context, so each relayed line names the span of the work that relays it.
    relayed = contextvars.copy_context()
    thread = threading.Thread(target=relayed.run, args=(poll,), name="phase-log", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=5)
        drain()


def _log_event(event: dict[str, Any]) -> None:
    if not logger.isEnabledFor(logging.INFO):
        return
    total = f"{event['current']}/{event['total']} " if event.get("total") else ""
    record = logger.makeRecord(
        logger.name,
        logging.INFO,
        __file__,
        0,
        "Phase %s: %s%s (%.0fs)",
        (
            event.get("label", event.get("phase")),
            total,
            event.get("message", ""),
            event.get("elapsed_seconds", 0.0),
        ),
        None,
    )
    # Legacy events have no timestamp. A malformed old entry must not stop progress.
    if isinstance(timestamp := event.get("timestamp"), str):
        with suppress(ValueError):
            created = datetime.fromisoformat(timestamp).timestamp()
            record = logging.makeLogRecord(
                record.__dict__ | {"created": created, "msecs": (created - int(created)) * 1000}
            )
    logger.handle(record)
