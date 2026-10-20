"""Is a newer release out: the button's check, and the daily check behind the banner."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from immich_memories import update_check
from immich_memories.config.loader import Config
from immich_memories.update_check import UpdateStatus
from immich_memories.web.dependencies import current_config

router = APIRouter(prefix="/api/v1/updates", tags=["updates"])


@router.get("")
def check() -> UpdateStatus:
    """Ask GitHub now. Only the button calls this: nothing goes out until somebody asks."""
    return update_check.check_now()


@router.get("/daily")
def daily(config: Annotated[Config, Depends(current_config)]) -> UpdateStatus | None:
    """The daily check's answer for the banner; null when it is off or has no news to fail on."""
    return update_check.daily_update_status(config)
