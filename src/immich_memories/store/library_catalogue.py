"""Write the library's own account of a period into the store.

The read side lives next door in `library_overviews.py` and never writes. This is the only
writer: cataloguing owns the table. An account is content-addressed by everything that could
change it, so the same evidence read by the same producer is never paid for twice.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass

import sqlalchemy as sa

from immich_memories.db import Store
from immich_memories.db.tables import library_overviews
from immich_memories.store.batches import bank_rows, id_in, in_chunks

_KINDS = frozenset({"month", "year", "span", "month-part", "year-part", "span-part"})


@dataclass(frozen=True)
class LibraryAccount:
    """A navigational account whose complete child index remains available."""

    key: str
    kind: str
    period: str
    account: str
    children: tuple[str, ...]


class CatalogueStore:
    """Bank neutral accounts independently of a film's brief or duration."""

    def __init__(self, store: Store) -> None:
        self._store = store

    def accounts_for(self, keys: Sequence[str]) -> dict[str, LibraryAccount]:
        """Read exact revisions in bounded batches."""
        t = library_overviews
        found: dict[str, LibraryAccount] = {}
        with self._store.connect() as connection:
            for batch in in_chunks(connection, list(keys)):
                rows = connection.execute(
                    sa.select(t.c.node_key, t.c.kind, t.c.period, t.c.account, t.c.children).where(
                        id_in(connection, t.c.node_key, batch)
                    )
                )
                for row in rows:
                    found[str(row.node_key)] = _account(row)
        return found

    def fullest(self, kind: str, period: str) -> LibraryAccount | None:
        """The banked account of this period built over the most children, or None.

        The same choice the film's own read makes, so a window reuses the account a month or
        a year film would have read.
        """
        t = library_overviews
        with self._store.connect() as connection:
            rows = connection.execute(
                sa.select(t.c.node_key, t.c.kind, t.c.period, t.c.account, t.c.children).where(
                    t.c.kind == kind, t.c.period == period
                )
            ).all()
        accounts = [_account(row) for row in rows if str(row.account or "").strip()]
        return max(
            accounts, key=lambda row: (len(row.children), len(row.account), row.key), default=None
        )

    def remember(self, accounts: Sequence[LibraryAccount]) -> None:
        """Keep the first validated account of each exact evidence revision."""
        if any(account.kind not in _KINDS for account in accounts):
            raise ValueError("only period overviews belong here; episodes use EpisodeReadingStore")
        rows = [
            {
                "node_key": row.key,
                "kind": row.kind,
                "period": row.period,
                "account": row.account,
                "children": json.dumps(row.children),
            }
            for row in accounts
        ]
        bank_rows(self._store, library_overviews, rows, keys=("node_key",), update=())


def _account(row: sa.Row) -> LibraryAccount:
    return LibraryAccount(
        str(row.node_key),
        str(row.kind),
        str(row.period),
        str(row.account),
        tuple(json.loads(str(row.children))),
    )
