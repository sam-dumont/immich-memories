"""A two-order block vote bank in the store, as the mapping `vote_blocks` reads and writes.

A bank is named (`memory-worthy`, `thesis-fit`) and scoped to one film's case key. Its
top-level entries are block answers, keyed by the digest of the exact question, plus two
per-row sections (`rows`, `rows-one-order`). The mapping records which entries changed, and
`save` writes only those, in one transaction: a vote saves after every block, and rewriting
the whole bank each time was the old file's quadratic cost.

Two runs sharing a bank can only add different keys or the same answer twice (a key is its
whole question), so the last writer of a key wins and nothing another run banked is dropped.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from immich_memories.analysis.editorial_block_votes import ONE_ORDER_ROWS
from immich_memories.db import Store
from immich_memories.db.tables import vote_bank_entries
from immich_memories.store.batches import bank_rows

ROW_SECTIONS = ("rows", ONE_ORDER_ROWS)
_KEYS = ("bank", "scope", "section", "entry_key")


class _Section(dict):
    """One per-row section; every write marks the row changed."""

    def __init__(self, name: str, entries: dict[str, Any], changed: set[tuple[str, str]]):
        super().__init__(entries)
        self._name = name
        self._changed = changed

    def __setitem__(self, key: str, value: Any) -> None:
        super().__setitem__(key, value)
        self._changed.add((self._name, key))

    def update(self, *args: Any, **kwargs: Any) -> None:
        for key, value in dict(*args, **kwargs).items():
            self[key] = value

    def setdefault(self, key: str, default: Any = None) -> Any:
        if key not in self:
            self[key] = default
        return self[key]


class VoteBank(dict):
    """One vote bank's entries as they stood when opened, plus what this run adds."""

    def __init__(self, store: Store, bank: str, scope: str) -> None:
        super().__init__()
        self._store = store
        self._bank = bank
        self._scope = scope
        self._changed: set[tuple[str, str]] = set()
        sections: dict[str, dict[str, Any]] = {name: {} for name in ROW_SECTIONS}
        with store.connect() as connection:
            rows = connection.execute(
                sa.select(
                    vote_bank_entries.c.section,
                    vote_bank_entries.c.entry_key,
                    vote_bank_entries.c.value,
                ).where(vote_bank_entries.c.bank == bank, vote_bank_entries.c.scope == scope)
            )
            for row in rows:
                if row.section:
                    sections.setdefault(row.section, {})[row.entry_key] = row.value
                else:
                    dict.__setitem__(self, row.entry_key, row.value)
        for name, entries in sections.items():
            if entries:
                dict.__setitem__(self, name, _Section(name, entries, self._changed))

    def __setitem__(self, key: str, value: Any) -> None:
        if key in ROW_SECTIONS:
            value = _Section(key, dict(value), self._changed)
            self._changed.update((key, name) for name in value)
        else:
            self._changed.add(("", key))
        super().__setitem__(key, value)

    def setdefault(self, key: str, default: Any = None) -> Any:
        if key not in self:
            self[key] = {} if default is None else default
        return self[key]

    def save(self) -> None:
        """Write every entry changed since the last save."""
        rows = []
        for section, key in sorted(self._changed):
            value = self[section][key] if section else self[key]
            rows.append(
                {
                    "bank": self._bank,
                    "scope": self._scope,
                    "section": section,
                    "entry_key": key,
                    "value": value,
                }
            )
        bank_rows(self._store, vote_bank_entries, rows, _KEYS)
        self._changed.clear()
