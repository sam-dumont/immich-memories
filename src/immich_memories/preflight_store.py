"""Preflight surfacing of the store/legacy-import warnings an upgrading `--config` user needs."""

from __future__ import annotations

from immich_memories.config import Config
from immich_memories.preflight import CheckResult, CheckStatus
from immich_memories.store_migration_notice import store_migration_warnings


def check_store_location(config: Config) -> CheckResult:
    """Flag a store or legacy import an upgrading `--config` user could otherwise miss."""
    warnings = store_migration_warnings(config)
    if not warnings:
        return CheckResult(
            name="Store location", status=CheckStatus.OK, message="Store location unchanged"
        )
    return CheckResult(
        name="Store location",
        status=CheckStatus.WARNING,
        message="This config's store or legacy import needs attention",
        details=" ".join(warnings),
    )
