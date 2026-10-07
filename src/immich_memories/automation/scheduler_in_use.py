"""Which scheduler is actually driving automation, for `auto status` (#2212)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from immich_memories.automation.in_process_scheduler import _slot_today

if TYPE_CHECKING:
    from immich_memories.automation.system_scheduler import SchedulerStatus
    from immich_memories.config_loader import Config

BUILT_IN_TIMER = "built-in timer"
EXTERNAL_TRIGGER = "external trigger"


@dataclass(frozen=True)
class SchedulerInUse:
    """The schedulers that can wake automation right now, and one line saying so."""

    in_use: list[str] = field(default_factory=list)
    summary: str = ""
    next_run: datetime | None = None


def _timer_part(config: Config, now: datetime) -> tuple[str, datetime]:
    slot = _slot_today(now, config.automation.daily_at)
    next_run = slot if now < slot else slot + timedelta(days=1)
    zone = now.tzname() or str(now.tzinfo)
    text = (
        f"{BUILT_IN_TIMER} (enabled, daily at {config.automation.daily_at} {zone}, "
        f"next firing {next_run.strftime('%Y-%m-%d %H:%M')})"
    )
    return text, next_run


def _unit_part(system: SchedulerStatus) -> str:
    state = "active" if system.active else "inactive" if system.active is False else "state unknown"
    return f"{system.platform}, installed, {state}"


def _trigger_part(last_trigger: datetime | None) -> str:
    when = (
        f"last trigger {last_trigger.astimezone().strftime('%Y-%m-%d %H:%M')}"
        if last_trigger is not None
        else "no trigger yet"
    )
    return f"{EXTERNAL_TRIGGER} (POST /api/trigger), {when}"


def describe_scheduler(
    config: Config,
    system: SchedulerStatus,
    last_trigger: datetime | None,
    *,
    now: datetime | None = None,
) -> SchedulerInUse:
    """Name every scheduler in use: the built-in timer, an installed unit, an external trigger.

    A crontab that cannot be read is not evidence of anything, so it is never named.
    """
    clock = now or datetime.now().astimezone()
    names: list[str] = []
    parts: list[str] = []
    next_run: datetime | None = None
    if config.automation.enabled:
        text, next_run = _timer_part(config, clock)
        names.append(BUILT_IN_TIMER)
        parts.append(text)
    if system.installed:
        names.append(system.platform)
        parts.append(_unit_part(system))
    if config.server.trigger_token or last_trigger is not None:
        names.append(EXTERNAL_TRIGGER)
        parts.append(_trigger_part(last_trigger))
    summary = "; ".join(parts) or (
        "none (built-in timer off, no system unit installed, no trigger token)"
    )
    return SchedulerInUse(in_use=names, summary=summary, next_run=next_run)
