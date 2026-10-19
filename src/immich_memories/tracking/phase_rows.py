"""Forward-only phase progress on a run or an automation attempt row, kept as appended rows."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from immich_memories.operations.phases import OperationalPhase, PhaseEvent


def advance_phase(
    connection: Connection,
    table: sa.Table,
    key: sa.Column[Any],
    value: str,
    event: PhaseEvent,
    events_key: sa.Column[Any],
) -> bool | None:
    """Append `event` to the row's phase log unless it would move the phase backwards.

    Returns None when no row has that key, False when the event is older than the phase the
    row already reached. The row is locked for the read so two writers cannot both append
    against the same previous phase. The write is one small INSERT plus the phase column,
    whatever the length of the log.
    """
    row = connection.execute(
        sa.select(table.c.last_phase).where(key == value).with_for_update()
    ).first()
    if row is None:
        return None
    previous = OperationalPhase(row.last_phase) if row.last_phase else None
    if previous is not None and event.phase.order < previous.order:
        return False
    connection.execute(sa.update(table).where(key == value).values(last_phase=event.phase.value))
    connection.execute(
        sa.insert(events_key.table), {events_key.name: value, "event": event.to_dict()}
    )
    return True


def read_phase_events(
    connection: Connection, events_key: sa.Column[Any], value: str, after: int = 0
) -> list[tuple[int, dict[str, Any]]]:
    """The owner's events with an id past `after`, oldest first, as `(id, event)`.

    A reader keeps the last id it saw and asks again from there, so each poll costs what is
    new, not the whole log.
    """
    events = events_key.table
    query = (
        sa.select(events.c.id, events.c.event)
        .where(events_key == value, events.c.id > after)
        .order_by(events.c.id)
    )
    return [(row.id, row.event) for row in connection.execute(query)]
