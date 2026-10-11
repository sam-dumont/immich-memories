"""Attempts a dead process left `running`: ended as interrupted, with one failure notice.

The automation lease is held for an attempt's whole life, from its row being written to its
end, and the operating system or the server drops it when the holder dies. So whoever holds
the lease next knows every `running` attempt it finds is an orphan (#2366).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from typing import TYPE_CHECKING

from immich_memories.automation.models import INTERRUPTED_REASON, AutomationAttempt, AutoOutcome
from immich_memories.automation.notifications import send_configured_notification

if TYPE_CHECKING:
    from immich_memories.automation.state_store import AutomationStateStore
    from immich_memories.config_loader import Config

logger = logging.getLogger(__name__)


def end_interrupted_attempts(
    config: Config, state: AutomationStateStore
) -> list[AutomationAttempt]:
    """End the orphaned attempts and notify once for each; the caller holds the lease."""
    ended = state.interrupt_running_attempts()
    for attempt in ended:
        logger.warning("Automation attempt %s was %s", attempt.id, INTERRUPTED_REASON)
        try:
            send_configured_notification(
                config=config,
                memory_type=attempt.memory_type or "automation",
                success=False,
                error=INTERRUPTED_REASON,
            )
        except Exception as exc:  # WHY: a notice is best-effort; the settling stands
            logger.warning("Failure notification could not be delivered (%s)", type(exc).__name__)
    return ended


def as_it_stands(
    attempt: AutomationAttempt | None, owner_alive: Callable[[], bool]
) -> AutomationAttempt | None:
    """An attempt as a reader should see it: `running` with no live owner reads interrupted.

    Computed, never written: a status read (a health probe polled every few seconds) must
    not change state or send a notice. ``owner_alive`` is asked only for a running one.
    """
    if attempt is None or attempt.outcome is not AutoOutcome.RUNNING or owner_alive():
        return attempt
    return replace(
        attempt, outcome=AutoOutcome.FAILED, reason=INTERRUPTED_REASON, error=INTERRUPTED_REASON
    )
