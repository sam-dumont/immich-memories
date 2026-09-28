"""Read the library's own account of a period, written by cataloguing.

Nothing here writes. Cataloguing owns the table; a film only ever reads it, and a library that
has not been catalogued has no row, which is not an error.
"""

from __future__ import annotations

import json
import logging

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from immich_memories.db import Store
from immich_memories.db.tables import library_overviews

logger = logging.getLogger(__name__)

_KINDS = ("month", "month-part", "year", "year-part", "span", "span-part")

# A month's key is "2024-02", a year's "2024" and a window's "2005-12-03..2026-09-23", so one
# period never holds two kinds.
_WHOLE = frozenset({"month", "year", "span"})


def library_period_account(store: Store, period: str) -> str:
    """The banked account of one period, or an empty string when the library has none.

    Two revisions of the same period can be banked; the one built over the most children is the
    fuller account. When only parts of the period were read, their accounts are joined in node
    key order, which is the only order the table records between them.
    """
    rows = _rows(store, period)
    whole = [(key, account, children) for key, kind, account, children in rows if kind in _WHOLE]
    if whole:
        return max(whole, key=lambda row: (len(row[2]), len(row[1]), row[0]))[1]
    parts = sorted(row for row in rows if row[1] not in _WHOLE)
    return "\n\n".join(account for _key, _kind, account, _children in parts)


def _rows(store: Store, period: str) -> list[tuple[str, str, str, list]]:
    t = library_overviews
    try:
        with store.connect() as connection:
            raw = connection.execute(
                sa.select(t.c.node_key, t.c.kind, t.c.account, t.c.children).where(
                    t.c.period == period, t.c.kind.in_(_KINDS)
                )
            ).all()
    except SQLAlchemyError as exc:
        logger.debug("No library overview for %s (%s): the period has no account", period, exc)
        return []
    rows = []
    for key, kind, account, children in raw:
        try:
            members = json.loads(str(children)) if children else []
        except (TypeError, json.JSONDecodeError):
            members = []
        if str(account or "").strip():
            rows.append((str(key), str(kind), str(account), list(members)))
    return rows
