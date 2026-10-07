"""The phase messages of one generation, shared by the terminal and an automation attempt."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from sqlalchemy.exc import SQLAlchemyError

from immich_memories.db import open_store

if TYPE_CHECKING:
    from immich_memories.config_loader import Config


class AttemptPhaseReporter:
    """Share semantic phase messages with CLI and an optional automation attempt.

    Also owns the heartbeat: a phase that goes quiet for half a minute repeats itself, so a
    scheduled run's log shows it is alive (#2219).
    """

    def __init__(
        self,
        config: Config,
        attempt_id: str | None,
        progress,
        task,
        heartbeat_seconds: float | None = None,
    ) -> None:
        from immich_memories.automation.state_store import AutomationStateStore
        from immich_memories.operations.phase_heartbeat import HEARTBEAT_SECONDS, PhaseHeartbeat

        self._attempt_id = attempt_id
        self._store = AutomationStateStore(open_store(config)) if attempt_id else None
        self._progress = progress
        self._task = task
        self._started = time.monotonic()
        self.heartbeat = PhaseHeartbeat(self._send, heartbeat_seconds or HEARTBEAT_SECONDS)

    def emit(self, phase, current: int, total: int, message: str) -> None:
        self.heartbeat.note(phase, current, total, message)
        self._send(phase, current, total, message)

    def _send(self, phase, current: int, total: int, message: str) -> None:
        from immich_memories.operations.phases import PhaseEvent

        now = time.monotonic()
        event = PhaseEvent(phase, current, total, message, now - self._started)
        self._started = now
        if self._store is not None and self._attempt_id is not None:
            try:
                self._store.update_phase(self._attempt_id, event)
            except (KeyError, OSError, RuntimeError, SQLAlchemyError):
                logging.getLogger(__name__).warning(
                    "Could not persist operational phase %s", phase.value
                )
        self._progress.update(self._task, description=event.message)
