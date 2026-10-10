"""Say a long phase is still alive, so a scheduled run's log never goes quiet (#2219).

A phase that reports once and then works for half an hour (the family-viewing check, the
picture review, a render) looks hung from `kubectl logs`. The heartbeat repeats the last
phase event, with the last count it knew, whenever nothing has reported for an interval.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from immich_memories.operations.phases import OperationalPhase

logger = logging.getLogger(__name__)

HEARTBEAT_SECONDS = 30.0

Emit = Callable[[OperationalPhase, int, int, str], None]


def _spent(seconds: float) -> str:
    return f"{int(seconds // 60)}m" if seconds >= 60 else f"{int(seconds)}s"


class PhaseHeartbeat:
    """Repeat the last phase event whenever `interval_seconds` pass without a new one."""

    def __init__(
        self,
        emit: Emit,
        interval_seconds: float = HEARTBEAT_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._emit = emit
        self._interval = interval_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._last: tuple[OperationalPhase, int, int, str] | None = None
        self._last_report = 0.0
        self._step_started = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def note(self, phase: OperationalPhase, current: int, total: int, message: str) -> None:
        """Record a real phase event: it resets the quiet timer and, when new, the step clock."""
        now = self._clock()
        with self._lock:
            previous = self._last
            if previous is None or previous[0] is not phase or previous[3] != message:
                self._step_started = now
            self._last = (phase, current, total, message)
            self._last_report = now

    def activity(self, message: str) -> None:
        """Remember a live substep without changing its outer phase or item counts."""
        now = self._clock()
        with self._lock:
            if self._last is None:
                return
            phase, current, total, previous = self._last
            if message != previous:
                self._step_started = now
            self._last = (phase, current, total, message)
            self._last_report = now

    def tick(self) -> bool:
        """Beat once if the phase has been quiet for a whole interval. True when it did."""
        now = self._clock()
        with self._lock:
            if self._last is None or self._last[0] is OperationalPhase.COMPLETE:
                return False
            if now - self._last_report < self._interval:
                return False
            phase, current, total, message = self._last
            self._last_report = now
            spent = _spent(now - self._step_started)
        try:
            self._emit(
                phase,
                current,
                total,
                f"{message}, process alive; no new progress ({spent} in this step)",
            )
        except Exception:  # WHY: a heartbeat must never fail the run it reports on
            logger.debug("Phase heartbeat could not be recorded", exc_info=True)
        return True

    def start(self) -> None:
        """Beat from a daemon thread until `stop`."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="phase-heartbeat", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _loop(self) -> None:
        wait = min(self._interval / 4, 5.0)
        while not self._stop.wait(wait):
            self.tick()
