"""The motion line each video carries into the pick, keyed like a caption.

A row belongs to one picture, one producer and the exact source metadata it was read from.
A changed source is a different digest, so its old row is simply not an answer any more.
`provenance` says what the row was produced from: the question asked, the keyframes read and
the measurement that made the source owe a line. Rows written before it existed leave it NULL,
so an old assessment can always be told from a current one (#1118).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa

from immich_memories.db import Store, now_db
from immich_memories.db.tables import motion_lines
from immich_memories.store.batches import bank_rows, id_in, in_chunks

DESCRIBED = "described"
UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class MotionLine:
    status: str
    text: str
    frames: int
    recorded: bool = False


def motion_line_row(
    *,
    asset_id: str,
    producer: str,
    source_digest: str,
    line: MotionLine,
    bytes_read: int,
    provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """One answer as the bank keeps it."""
    return {
        "asset_id": asset_id,
        "producer": producer,
        "source_digest": source_digest,
        "status": line.status,
        "text": line.text,
        "frames": line.frames,
        "bytes_read": bytes_read,
        "written_at": now_db(),
        "provenance": None if provenance is None else json.dumps(provenance, sort_keys=True),
    }


def remember_motion_lines(store: Store, rows: Sequence[Mapping[str, Any]]) -> None:
    """Replace whatever each producer said about an older version of the same picture."""
    latest = list({(row["asset_id"], row["producer"]): row for row in rows}.values())
    if latest:
        bank_rows(store, motion_lines, latest, keys=("asset_id", "producer"))


def settled_motion_lines(
    store: Store, digests: Mapping[str, str], producer: str
) -> dict[str, MotionLine]:
    """The rows that still answer for these pictures as they are now."""
    settled: dict[str, MotionLine] = {}
    t = motion_lines
    with store.connect() as connection:
        for batch in in_chunks(connection, list(digests)):
            rows = connection.execute(
                sa.select(
                    t.c.asset_id,
                    t.c.source_digest,
                    t.c.status,
                    t.c.text,
                    t.c.frames,
                    t.c.provenance,
                ).where(t.c.producer == producer, id_in(connection, t.c.asset_id, batch))
            )
            row: Any
            for row in rows:
                asset_id, digest, status, text, frames, recorded = row
                if digest == digests[asset_id] and status in {DESCRIBED, UNAVAILABLE}:
                    settled[asset_id] = MotionLine(status, text, frames, recorded is not None)
    return settled
