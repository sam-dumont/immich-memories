"""Whether the store holds saved settings the loader ignores.

A row under `auth.*` or `server.*`, or a value with a `${VAR}` reference, was saved before
those were refused. The loader skips it with a warning; this names each key, never its value,
so the operator can set it in config.yaml or the environment instead.
"""

from __future__ import annotations

from immich_memories.config_loader import Config
from immich_memories.preflight import CheckResult, CheckStatus
from immich_memories.settings_store import settings_store

_NAME = "Saved settings"


def check_stored_settings(config: Config) -> CheckResult:
    """An error naming every ignored stored key; OK when the store has none."""
    try:
        store = settings_store(config, create=False)
        ignored = store.ignored() if store is not None else {}
    except Exception as error:  # noqa: BLE001 -- an unreachable store is its own check's finding
        return CheckResult(
            _NAME, CheckStatus.WARNING, "Saved settings could not be read", type(error).__name__
        )
    if not ignored:
        return CheckResult(_NAME, CheckStatus.OK, "Every saved setting is in use")
    details = "; ".join(f"{key}: {reason}" for key, reason in sorted(ignored.items()))
    return CheckResult(
        _NAME,
        CheckStatus.ERROR,
        f"{len(ignored)} saved setting(s) ignored; set them in config.yaml or the environment",
        details,
    )

