"""When the HTTP trigger last started a run, for `auto status`.

An attempt's start reason is replaced by its outcome when it finishes, so the history
cannot say which attempts a caller asked for. A stamp beside the automation lease can; it
is per host, like the lease file, and only informs a status line.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from immich_memories.config_loader import Config

logger = logging.getLogger(__name__)


def _stamp(config: Config) -> Path:
    return config.cache.database_path.parent / ".last-trigger"


def record_trigger(config: Config, when: datetime | None = None) -> None:
    """Remember that the trigger API just started a run. Never fails the request."""
    moment = when or datetime.now(tz=UTC)
    try:
        _stamp(config).write_text(moment.isoformat(), encoding="utf-8")
    except OSError:
        logger.debug("Could not record the trigger time", exc_info=True)


def read_last_trigger(config: Config) -> datetime | None:
    """The last recorded trigger, or None when there is none or the stamp is unreadable."""
    try:
        return datetime.fromisoformat(_stamp(config).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
