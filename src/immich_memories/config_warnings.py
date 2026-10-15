"""The warnings loading a config gives, collected for the Settings page instead of the log.

A config load names removed, unknown, merged and no-longer-supported keys, and a reader set up
but switched off, as log warnings (`config_loader.py`, `config_unsupported.py`). Someone who
only uses the web client never reads the container log, so the Settings page loads the config
again and shows the same lines. They name keys, never values.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from immich_memories import config_unsupported
from immich_memories.config_loader import Config

_CONFIG_LOGGERS = "immich_memories.config"
# Some modules name their logger only when they first warn, so it may not exist yet.
_NAMED_ON_FIRST_WARNING = ("immich_memories.config_loader",)


@contextmanager
def _collected(into: list[str]) -> Iterator[None]:
    """Take this thread's config warnings off the log and into `into`."""
    thread = threading.get_ident()

    def keep(record: logging.LogRecord) -> bool:
        if record.thread != thread or record.levelno < logging.WARNING:
            return True
        into.append(record.getMessage())
        return False

    existing = [
        name for name in logging.root.manager.loggerDict if name.startswith(_CONFIG_LOGGERS)
    ]
    loggers = [logging.getLogger(name) for name in {*existing, *_NAMED_ON_FIRST_WARNING}]
    # WHY: a warning is said once per process; this load must say it again, to the page.
    said = config_unsupported._said.copy()
    config_unsupported._said.clear()
    for logger in loggers:
        logger.addFilter(keep)
    try:
        yield
    finally:
        for logger in loggers:
            logger.removeFilter(keep)
        config_unsupported._said.update(said)


def config_warnings(path: Path) -> list[str]:
    """Every warning loading the config at `path` gives, in the order given, each once."""
    found: list[str] = []
    with _collected(found):
        Config.from_yaml(path)
    return list(dict.fromkeys(found))
