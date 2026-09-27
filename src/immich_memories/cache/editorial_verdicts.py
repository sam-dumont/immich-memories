"""What a picture IS, remembered across every memory it could appear in.

Cull answers two durable questions and one contextual one. Whether a frame is a
photographed screen or a document, and whether it came out at all, are facts
about the picture: true in a month, a year, a person's spotlight, a trip. That
a frame is "one of several alike" is not — it is a fact about what it happened
to sit beside, and it is deliberately not stored here.

So a year stops paying to re-decide the same fifteen thousand pictures twelve
times, and a Person or Trip memory inherits the judgement rather than needing
Cull to be gentler on a corpus that was already filtered.

The cost of being wrong rises with the reuse: a bad cull used to spoil one
video and now follows the picture everywhere. That is why the trace says a
visual was culled on a remembered verdict rather than quietly omitting it, why
a star still outranks anything stored here, and why the table can be emptied at
any time — it costs only the calls it saved.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import sqlalchemy as sa

from immich_memories.db import Store, now_db
from immich_memories.db.tables import editorial_verdicts
from immich_memories.store.batches import bank_rows, id_in, in_chunks

# The pass judged this picture and removed nothing. It is stored because a bank
# of rejects only can never withdraw one, and because no row at all means the
# pass never looked, which is a different answer. No Cull bucket uses this word.
KEPT_VERDICT = "kept"


class EditorialVerdicts:
    """Durable per-asset Cull verdicts, scoped to what the buckets meant."""

    def __init__(self, store: Store) -> None:
        self._store = store

    def remember(self, verdicts: Iterable[tuple[str, str]], *, pass_version: str) -> None:
        """Store one standing verdict per asset; the most recent look wins.

        Takes plain (asset, bucket) pairs so the cache layer stays ignorant of
        the editorial contracts, and so the caller decides which buckets are
        durable enough to remember.
        """
        decided_at = now_db()
        rows = {
            asset_id: {
                "asset_id": asset_id,
                "pass_version": pass_version,
                "bucket": bucket,
                "decided_at": decided_at,
            }
            for asset_id, bucket in verdicts
        }
        if not rows:
            return
        bank_rows(
            self._store, editorial_verdicts, list(rows.values()), keys=("asset_id", "pass_version")
        )

    def recall(self, asset_ids: Sequence[str], *, pass_version: str) -> dict[str, str]:
        """The standing verdicts for these assets under this definition."""
        t = editorial_verdicts
        recalled: dict[str, str] = {}
        # A lifetime window holds more pictures than one statement may bind.
        with self._store.connect() as connection:
            for chunk in in_chunks(connection, list(asset_ids)):
                rows = connection.execute(
                    sa.select(t.c.asset_id, t.c.bucket).where(
                        t.c.pass_version == pass_version, id_in(connection, t.c.asset_id, chunk)
                    )
                )
                recalled.update({str(asset_id): str(bucket) for asset_id, bucket in rows})
        return recalled
