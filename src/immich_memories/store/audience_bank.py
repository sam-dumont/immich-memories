"""The library's audience bank in the store: model answers by evidence key, holds by slot.

`AudienceBank` (analysis/editorial_structure_audience.py) owns the rules; this module only
reads and writes them. Holds change a batch at a time: the batch's pictures are locked, read
fresh and merged inside one transaction, so two cuts holding one picture at once can't lose the
stricter hold, and a crash costs at most the batch in hand.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Connection

from immich_memories.db import Store
from immich_memories.db.tables import audience_answers, audience_holds
from immich_memories.store.batches import id_in, in_chunks, upsert_rows

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


def change_holds(
    store: Store, merge_of: Mapping[str, Callable[[Slots], Slots | None]]
) -> dict[str, Slots]:
    """Merge a batch of pictures' holds with the store's copies in one transaction.

    `merge_of` maps a picture to a function from its slots as they stand now to the new
    slots, or None when they don't change. Returns what stands after for every picture in the
    batch. A slot the new slots lack is dropped (a text hold cast under an older prompt).
    Writers lock their pictures in one sorted order, so overlapping batches queue instead of
    deadlocking; unchanged pictures cost no write.
    """
    ids = sorted(merge_of)
    if not ids:
        return {}
    with store.begin() as connection:
        _lock_pictures(connection, ids)
        current: dict[str, Slots] = {}
        for chunk in in_chunks(connection, ids):
            current |= _slots(
                connection.execute(
                    sa.select(audience_holds).where(
                        id_in(connection, audience_holds.c.asset_id, chunk)
                    )
                )
            )
        after, gone, rows = {}, [], []
        for asset_id in ids:
            before = current.get(asset_id, {})
            merged = merge_of[asset_id](before.copy())
            after[asset_id] = before if merged is None else merged
            if merged is None:
                continue
            gone += [{"a": asset_id, "s": slot} for slot in set(before) - set(merged)]
            rows += [{"asset_id": asset_id, "slot": k, "hold": v} for k, v in merged.items()]
        if gone:
            connection.execute(
                sa.delete(audience_holds).where(
                    audience_holds.c.asset_id == sa.bindparam("a"),
                    audience_holds.c.slot == sa.bindparam("s"),
                ),
                gone,
            )
        _write_holds(connection, rows)
        return after


def _write_holds(connection: Connection, rows: list[dict[str, Any]]) -> None:
    """Upsert the changed slots. On PostgreSQL the batch goes as three arrays in one
    statement: a pipelined executemany costs a round trip's work per row, about twice
    SQLite's time for the same batch."""
    if not rows:
        return
    if connection.dialect.name != "postgresql":
        upsert_rows(connection, audience_holds, rows, ("asset_id", "slot"))
        return
    arrays = sa.select(
        sa.func.unnest(
            sa.bindparam("a", [row["asset_id"] for row in rows], type_=postgresql.ARRAY(sa.Text)),
            sa.bindparam("s", [row["slot"] for row in rows], type_=postgresql.ARRAY(sa.Text)),
            sa.bindparam(
                "h", [json.dumps(row["hold"]) for row in rows], type_=postgresql.ARRAY(sa.Text)
            ),
        )
        .table_valued("asset_id", "slot", "hold")
        .render_derived()
    ).subquery()
    insert = postgresql.insert(audience_holds).from_select(
        ["asset_id", "slot", "hold"],
        sa.select(arrays.c.asset_id, arrays.c.slot, sa.cast(arrays.c.hold, sa.JSON)),
    )
    connection.execute(
        insert.on_conflict_do_update(
            index_elements=["asset_id", "slot"], set_={"hold": insert.excluded.hold}
        )
    )


def _slots(rows) -> dict[str, Slots]:
    held: dict[str, Slots] = {}
    for row in rows:
        held.setdefault(row.asset_id, {})[row.slot] = row.hold
    return held


def _lock_pictures(connection: Connection, asset_ids: list[str]) -> None:
    """Serialise hold writers on these pictures. SQLite's `BEGIN IMMEDIATE` already serialises
    every writer; PostgreSQL takes one transaction advisory lock per picture, in ascending key
    order, in a single statement."""
    if connection.dialect.name != "postgresql":
        return
    keys = sorted(
        {
            int.from_bytes(
                hashlib.sha256(f"audience-hold:{asset_id}".encode()).digest()[:8],
                "big",
                signed=True,
            )
            for asset_id in asset_ids
        }
    )
    connection.execute(
        sa.text("SELECT pg_advisory_xact_lock(k) FROM unnest(CAST(:keys AS bigint[])) AS k"),
        {"keys": keys},
    )
