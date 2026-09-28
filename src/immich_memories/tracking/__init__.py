"""Run versioning and statistics tracking for pipeline executions."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from immich_memories.tracking.models import (
        DeliveryStatus,
        PhaseStats,
        RunMetadata,
        SystemInfo,
    )
    from immich_memories.tracking.run_database import RunDatabase
    from immich_memories.tracking.run_id import generate_run_id, is_valid_run_id, parse_run_id
    from immich_memories.tracking.run_lifecycle_errors import (
        DuplicateRunError,
        InvalidRunLifecycleError,
    )
    from immich_memories.tracking.run_tracker import RunTracker, format_duration
    from immich_memories.tracking.system_info import capture_system_info

# WHY lazy: the API client and the renderer import tracking.timed for spans; an eager
# package init would load SQLAlchemy and the run database into every one of them.
_EXPORTS = {
    "DeliveryStatus": "models",
    "PhaseStats": "models",
    "RunMetadata": "models",
    "SystemInfo": "models",
    "RunDatabase": "run_database",
    "generate_run_id": "run_id",
    "is_valid_run_id": "run_id",
    "parse_run_id": "run_id",
    "DuplicateRunError": "run_lifecycle_errors",
    "InvalidRunLifecycleError": "run_lifecycle_errors",
    "RunTracker": "run_tracker",
    "format_duration": "run_tracker",
    "capture_system_info": "system_info",
}


def __getattr__(name: str) -> Any:
    if (module := _EXPORTS.get(name)) is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f"{__name__}.{module}"), name)
    globals()[name] = value
    return value


__all__ = [
    "PhaseStats",
    "DeliveryStatus",
    "DuplicateRunError",
    "InvalidRunLifecycleError",
    "RunDatabase",
    "RunMetadata",
    "RunTracker",
    "SystemInfo",
    "capture_system_info",
    "format_duration",
    "generate_run_id",
    "is_valid_run_id",
    "parse_run_id",
]
