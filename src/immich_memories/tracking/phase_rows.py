"""Forward-only phase progress on a run or an automation attempt row."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from immich_memories.operations.phases import OperationalPhase, PhaseEvent


def advance_phase(
    connection: Connection, table: sa.Table, key: sa.Column[Any], value: str, event: PhaseEvent
) -> bool | None:
    """Append `event` to the row's phase log unless it would move the phase backwards.

    Returns None when no row has that key, False when the event is older than the phase the
    row already reached. The row is locked for the read so two writers cannot both append
    against the same previous phase.
    """
    row = connection.execute(
        sa.select(table.c.last_phase, table.c.phase_events).where(key == value).with_for_update()
    ).first()
    if row is None:
        return None
    previous = OperationalPhase(row.last_phase) if row.last_phase else None
    if previous is not None and event.phase.order < previous.order:
        return False
    connection.execute(
        sa.update(table)
        .where(key == value)
        .values(
            last_phase=event.phase.value,
            phase_events=[*(row.phase_events or []), event.to_dict()],
        )
    )
    return True
