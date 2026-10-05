"""Warnings for a `--config` user upgrading past the store/log location fix (#2076).

Before that fix, every run's store and legacy import both read from `~/.immich-memories`
regardless of `--config`. Two things can now silently look empty or incomplete for someone
upgrading: the store, which moved beside a non-default config, and the one-time legacy
import, which still only reads `~/.immich-memories` unless told otherwise. Both warnings are
collected here so the CLI, the web server and `preflight` all surface the same text.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from immich_memories.config_loader import Config

logger = logging.getLogger(__name__)


def store_migration_warnings(config: Config) -> list[str]:
    """Every reason this config's store or legacy import could surprise an upgrading user."""
    from immich_memories.db.bootstrap import store_relocation_warning
    from immich_memories.store.legacy_imports import legacy_import_skip_warning

    warnings = (store_relocation_warning(config), legacy_import_skip_warning(config))
    return [warning for warning in warnings if warning]


def log_store_migration_warnings(config: Config) -> None:
    """Log each warning once, at startup."""
    for warning in store_migration_warnings(config):
        logger.warning(warning)
