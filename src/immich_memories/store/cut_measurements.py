"""The facts a cut measures: a Live Photo's motion residual, a clip's speech, and how two
Live companions' clocks relate.

A row belongs to one picture (or one pair of companions), one producer and the exact source
metadata it was measured from, like a caption or a motion line. A changed source is a different digest, so its old
row stops being an answer. No row means nobody measured, never "measured nothing": a clip
with no speech in it is an empty region list under a row that exists.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy import Table
from sqlalchemy.exc import SQLAlchemyError

from immich_memories.db import Store, now_db
from immich_memories.db.tables import live_clock_offsets, motion_residuals, speech_regions
from immich_memories.store.batches import bank_rows, id_in, in_chunks, upsert_rows

logger = logging.getLogger(__name__)


BATCH_ROWS = 32


class PendingMeasurements:
    """Measurements a cut banks as it goes: one write every `size` rows and on exit.

    A measurement costs a download and a decode, so a crash may cost at most one batch of
    them; the next cut measures those again.
    """

    def __init__(self, store: Store, size: int = BATCH_ROWS) -> None:
        self._store = store
        self._size = size
        self._rows: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}

    def motion_residual(
        self, *, asset_id: str, producer: str, source_digest: str, measured: Mapping[str, Any]
    ) -> None:
        """Replace whatever this producer measured on an older version of the same picture."""
        self._add(motion_residuals, asset_id, producer, source_digest, dict(measured))

    def speech_regions(
        self,
        *,
        asset_id: str,
        producer: str,
        source_digest: str,
        regions: Sequence[tuple[float, float]],
    ) -> None:
        """An empty list is an answer: this detector heard no speech in this exact source."""
        measured = [[start, end] for start, end in regions]
        self._add(speech_regions, asset_id, producer, source_digest, measured)

    def clock_offset(
        self, *, pair: tuple[str, str], producer: str, source_digest: str, seconds: float | None
    ) -> None:
        """None is an answer: the files share no content this measurement can trust."""
        self._add(
            live_clock_offsets, _pair_key(pair), producer, source_digest, {"seconds": seconds}
        )

    def _add(self, table: Table, asset_id: str, producer: str, digest: str, measured: Any) -> None:
        self._rows.setdefault(table.name, {})[(asset_id, producer)] = {
            "asset_id": asset_id,
            "producer": producer,
            "source_digest": digest,
            "measured": json.dumps(measured, sort_keys=True),
            "written_at": now_db(),
        }
        if sum(len(rows) for rows in self._rows.values()) >= self._size:
            self.flush()

    def flush(self) -> None:
        pending, self._rows = self._rows, {}
        if not pending:
            return
        tables = {t.name: t for t in (motion_residuals, speech_regions, live_clock_offsets)}
        if len(pending) == 1:
            [(name, rows)] = pending.items()
            bank_rows(self._store, tables[name], list(rows.values()), keys=("asset_id", "producer"))
            return
        with self._store.begin() as connection:
            for name, rows in pending.items():
                upsert_rows(
                    connection, tables[name], list(rows.values()), keys=("asset_id", "producer")
                )

    def __enter__(self) -> PendingMeasurements:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.flush()


def _banked(
    store: Store, table: Table, digests: Mapping[str, str], producer: str
) -> dict[str, Any]:
    """Rows still answering for these sources; an unreachable store answers nobody."""
    banked: dict[str, Any] = {}
    try:
        with store.connect() as connection:
            for batch in in_chunks(connection, list(digests)):
                rows = connection.execute(
                    sa.select(table.c.asset_id, table.c.source_digest, table.c.measured).where(
                        table.c.producer == producer, id_in(connection, table.c.asset_id, batch)
                    )
                )
                for asset_id, digest, measured in rows:
                    if digest == digests[str(asset_id)]:
                        banked[str(asset_id)] = json.loads(str(measured))
    except SQLAlchemyError as exc:
        logger.debug("%s unreadable (%s): nothing banked", table.name, exc)
        return {}
    return banked


def banked_motion_residuals(
    store: Store, digests: Mapping[str, str], producer: str
) -> dict[str, dict[str, Any]]:
    """The motion measurements that still answer for these pictures as they are now."""
    return {
        asset_id: measured
        for asset_id, measured in _banked(store, motion_residuals, digests, producer).items()
        if isinstance(measured, dict)
    }


def banked_speech_regions(
    store: Store, digests: Mapping[str, str], producer: str
) -> dict[str, tuple[tuple[float, float], ...]]:
    """The speech regions that still answer for these clips as they are now."""
    return {
        asset_id: tuple((float(pair[0]), float(pair[1])) for pair in measured)
        for asset_id, measured in _banked(store, speech_regions, digests, producer).items()
        if isinstance(measured, list)
    }


def _pair_key(pair: tuple[str, str]) -> str:
    # A join belongs to both companions, in shutter order; ids never hold a newline.
    return f"{pair[0]}\n{pair[1]}"


def measured_clock_offsets(
    store: Store, producer: str
) -> dict[tuple[str, str], tuple[str, float | None]]:
    """Every join this producer measured, with the source digest it was measured on.

    A cut asks about bursts one at a time; reading the producer's joins once answers all of
    them. An unreachable store answers nobody.
    """
    t = live_clock_offsets
    try:
        with store.connect() as connection:
            rows: list[Any] = list(
                connection.execute(
                    sa.select(t.c.asset_id, t.c.source_digest, t.c.measured).where(
                        t.c.producer == producer
                    )
                )
            )
    except SQLAlchemyError as exc:
        logger.debug("%s unreadable (%s): nothing banked", t.name, exc)
        return {}
    joins: dict[tuple[str, str], tuple[str, float | None]] = {}
    for key, digest, raw in rows:
        first, _newline, second = str(key).partition("\n")
        measured = json.loads(str(raw))
        if second and isinstance(measured, dict) and "seconds" in measured:
            seconds = measured["seconds"]
            joins[(first, second)] = (str(digest), float(seconds) if seconds is not None else None)
    return joins
