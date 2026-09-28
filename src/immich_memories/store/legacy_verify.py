"""Checking an import: every legacy row's key is in the store, holding the same values.

Problems name the table, the key and the columns that differ, never the values: a verify
report is safe to paste into an issue.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from immich_memories.store.batches import id_in, in_chunks


def verify_rows(
    connection: Connection,
    table: sa.Table,
    keys: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
    *,
    exact: bool = False,
) -> list[str]:
    """Each of `rows` (store-shaped, keyed by `keys`) that the store lacks or holds otherwise.

    Only the columns a row carries are compared. Floats compare to within rounding unless
    `exact`, which the owner's own records (decisions, people, special days) always use.
    """
    held = _held(connection, table, keys, rows)
    problems = []
    for row in rows:
        key = tuple(row[name] for name in keys)
        found = held.get(key)
        if found is None:
            problems.append(f"{table.name} {_shown(key)}: missing")
            continue
        differ = [name for name, value in row.items() if not _same(value, found[name], exact)]
        if differ:
            problems.append(f"{table.name} {_shown(key)}: {', '.join(differ)} differ")
    return problems


def unreadable(path: Path, error: Exception) -> str:
    """The problem line for a legacy file the verifier could not read."""
    return f"{path}: not readable ({error})"


def _held(
    connection: Connection,
    table: sa.Table,
    keys: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
) -> dict[tuple[Any, ...], Mapping[str, Any]]:
    first = table.c[keys[0]]
    wanted = sorted({row[keys[0]] for row in rows})
    textual = isinstance(first.type, sa.String)
    held: dict[tuple[Any, ...], Any] = {}
    for chunk in in_chunks(connection, wanted):
        match = id_in(connection, first, chunk) if textual else first.in_(chunk)
        for found in connection.execute(sa.select(table).where(match)).mappings():
            held[tuple(found[name] for name in keys)] = found
    return held


def _same(legacy: Any, stored: Any, exact: bool) -> bool:
    if not exact and isinstance(legacy, float) and isinstance(stored, float):
        return math.isclose(legacy, stored, rel_tol=1e-9, abs_tol=1e-12)
    return bool(legacy == stored)


def _shown(key: tuple[Any, ...]) -> str:
    return "/".join(str(part) for part in key)
