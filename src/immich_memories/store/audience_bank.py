"""The library's audience bank in the store: model answers by evidence key, holds by slot.

`AudienceBank` (analysis/editorial_structure_audience.py) owns the rules; this module only
reads and writes them. A hold is changed under a lock on its picture, read fresh inside the
same transaction, so two cuts holding one picture at once can't lose the stricter hold.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from immich_memories.db import Store
from immich_memories.db.tables import audience_answers, audience_holds
from immich_memories.store.batches import upsert_rows

Slots = dict[str, Any]


def load_answers(store: Store, answerer: str) -> dict[str, Any]:
    """Every answer `answerer` gave, by evidence key."""
    with store.connect() as connection:
        rows = connection.execute(
            sa.select(audience_answers.c.evidence_key, audience_answers.c.record).where(
                audience_answers.c.answerer == answerer
            )
        )
        return {row.evidence_key: row.record for row in rows}


def keep_answer(store: Store, answerer: str, key: str, record: dict[str, Any]) -> None:
    with store.begin() as connection:
        upsert_rows(
            connection,
            audience_answers,
            [{"answerer": answerer, "evidence_key": key, "record": record}],
            ("answerer", "evidence_key"),
        )


def load_holds(store: Store) -> dict[str, Slots]:
    """Every picture's banked hold slots, as the bank has them now."""
    with store.connect() as connection:
        return _slots(connection.execute(sa.select(audience_holds)))


def change_hold(store: Store, asset_id: str, merge: Callable[[Slots], Slots | None]) -> Slots:
    """Apply `merge` to the picture's slots as they stand in the store; return what stands after.

    `merge` returns the new slots, or None when the hold does not change. A slot the new
    slots lack is dropped (a text hold cast under an older prompt).
    """
    with store.begin() as connection:
        _lock_picture(connection, asset_id)
        current = _slots(
            connection.execute(
                sa.select(audience_holds).where(audience_holds.c.asset_id == asset_id)
            )
        ).get(asset_id, {})
        merged = merge(current.copy())
        if merged is None:
            return current
        gone = set(current) - set(merged)
        if gone:
            connection.execute(
                sa.delete(audience_holds).where(
                    audience_holds.c.asset_id == asset_id, audience_holds.c.slot.in_(gone)
                )
            )
        upsert_rows(
            connection,
            audience_holds,
            [{"asset_id": asset_id, "slot": slot, "hold": hold} for slot, hold in merged.items()],
            ("asset_id", "slot"),
        )
        return merged


def _slots(rows) -> dict[str, Slots]:
    held: dict[str, Slots] = {}
    for row in rows:
        held.setdefault(row.asset_id, {})[row.slot] = row.hold
    return held


def _lock_picture(connection: Connection, asset_id: str) -> None:
    """Serialise hold writers on one picture. SQLite's `BEGIN IMMEDIATE` already serialises
    every writer; PostgreSQL takes a transaction advisory lock named by the picture."""
    if connection.dialect.name != "postgresql":
        return
    digest = hashlib.sha256(f"audience-hold:{asset_id}".encode()).digest()
    key = int.from_bytes(digest[:8], "big", signed=True)
    connection.execute(sa.select(sa.func.pg_advisory_xact_lock(key)))
