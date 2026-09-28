"""Head facts per asset: (asset, head, version) -> label, banked in the store's `head_facts`."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import TracebackType
from typing import Any

import sqlalchemy as sa

from immich_memories.db import Store, now_db
from immich_memories.db.tables import head_facts
from immich_memories.store.batches import bank_rows, id_in, in_chunks
from immich_memories.triage.heads import HeadFact

# Pictures per write when a producer banks as it goes: a crash costs at most this many.
BATCH_PICTURES = 32


class HeadFactStore:
    def __init__(self, store: Store) -> None:
        self._store = store

    def remember_facts(self, facts: Mapping[str, Sequence[HeadFact]], *, encoder_key: str) -> None:
        """Bank a batch of pictures' head answers in one transaction."""
        self.remember_rows(_rows(facts, encoder_key))

    def remember_rows(self, rows: Sequence[Mapping[str, Any]]) -> None:
        # A key twice in one statement is refused by PostgreSQL; the later answer wins.
        latest = {(r["asset_id"], r["head"], r["version"]): r for r in rows}
        if not latest:
            return
        bank_rows(
            self._store, head_facts, list(latest.values()), keys=("asset_id", "head", "version")
        )

    def facts_for(
        self, asset_ids: Sequence[str], *, head: str, version: str
    ) -> dict[str, HeadFact]:
        t = head_facts
        found: dict[str, HeadFact] = {}
        with self._store.connect() as connection:
            for chunk in in_chunks(connection, list(asset_ids)):
                rows = connection.execute(
                    sa.select(t.c.asset_id, t.c.label, t.c.confidence).where(
                        t.c.head == head,
                        t.c.version == version,
                        id_in(connection, t.c.asset_id, chunk),
                    )
                )
                found.update(
                    (
                        row[0],
                        HeadFact(
                            head=head, label=row[1], confidence=float(row[2]), version=version
                        ),
                    )
                    for row in rows
                )
        return found


class PendingHeadFacts:
    """Head answers a producer banks as it goes, written every `size` pictures and on exit."""

    def __init__(self, bank: HeadFactStore, size: int = BATCH_PICTURES) -> None:
        self._bank = bank
        self._size = size
        self._rows: list[dict[str, Any]] = []
        self._pictures: set[str] = set()

    def add(self, asset_id: str, facts: Sequence[HeadFact], *, encoder_key: str) -> None:
        self._rows.extend(_rows({asset_id: facts}, encoder_key))
        self._pictures.add(asset_id)
        if len(self._pictures) >= self._size:
            self.flush()

    def flush(self) -> None:
        rows, self._rows, self._pictures = self._rows, [], set()
        self._bank.remember_rows(rows)

    def __enter__(self) -> PendingHeadFacts:
        return self

    def __exit__(
        self,
        _type: type[BaseException] | None,
        _error: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        # Whatever was decided before a stop is kept, as a per-picture commit kept it.
        self.flush()


def _rows(facts: Mapping[str, Sequence[HeadFact]], encoder_key: str) -> list[dict[str, Any]]:
    decided_at = now_db()
    return [
        {
            "asset_id": asset_id,
            "head": f.head,
            "version": f.version,
            "label": f.label,
            "confidence": f.confidence,
            "encoder_key": encoder_key,
            "decided_at": decided_at,
        }
        for asset_id, decided in facts.items()
        for f in decided
    ]
