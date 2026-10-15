"""The warnings loading a config gives, collected for the Settings page instead of the log.

A config load names removed, unknown, merged and no-longer-supported keys, and a reader set up
but switched off, as log warnings (`config/loader.py`, `config/unsupported.py`). Someone who
only uses the web client never reads the container log, so the Settings page loads the config
again and shows the same lines. They name keys, never values.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from immich_memories.config import unsupported as config_unsupported
from immich_memories.config.loader import Config
from immich_memories.logging_config import redact_secrets

_CONFIG_LOGGERS = "immich_memories.config"
# Some modules name their logger only when they first warn, so it may not exist yet.
_NAMED_ON_FIRST_WARNING = ("immich_memories.config.loader",)


@contextmanager
def _collected(into: list[str]) -> Iterator[None]:
    """Take this thread's config warnings off the log and into `into`."""
    thread = threading.get_ident()

    def keep(record: logging.LogRecord) -> bool:
        if record.thread != thread or record.levelno < logging.WARNING:
            return True
        # WHY: the handler-level redaction never sees a record this filter keeps off the log.
        into.append(redact_secrets(record.getMessage()))
        return False

    existing = [
        name for name in logging.root.manager.loggerDict if name.startswith(_CONFIG_LOGGERS)
    ]
    loggers = [logging.getLogger(name) for name in {*existing, *_NAMED_ON_FIRST_WARNING}]
    for logger in loggers:
        logger.addFilter(keep)
    try:
        # WHY: a warning is said once per process; this load must say it again, to the page.
        with config_unsupported.every_warning_said_again():
            yield
    finally:
        for logger in loggers:
            logger.removeFilter(keep)


def config_warnings(path: Path) -> list[str]:
    """Every warning loading the config at `path` gives, in the order given, each once."""
    found: list[str] = []
    with _collected(found):
        Config.from_yaml(path)
    return list(dict.fromkeys(found))
