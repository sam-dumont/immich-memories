"""The owner's own word on a picture: clear its hold, or never use it.

Kept as `source='owner'` rows in the store's `asset_flags` table, the rows the audience
gate and the material builder already read (`editorial_shareability.load_flags`). This module
is their only writer. A picture carries at most one owner decision: a new one replaces the old
in the same transaction, so two writers (the web page and the CLI) can't leave a picture both
cleared and never used. Each write is a single store transaction, which is why no file lock is
needed here, unlike the JSON banks (#1266).

A Live Photo is one picture to its owner, so a decision on its still covers its motion clip
too, when the store knows the clip.
"""

from __future__ import annotations

import json
from collections.abc import Iterable

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from immich_memories.analysis.editorial_shareability import (
    NEVER_AUTO,
    OWNER_CLEARANCES,
    OWNER_CLEARED,
    OWNER_SOURCE,
)
from immich_memories.db import Store, now_db
from immich_memories.db.tables import annotation_assets, asset_flags
from immich_memories.store.batches import id_in, in_chunks, upsert_rows
from immich_memories.store.editorial_preparation import now

CLEAR_HOLD = OWNER_CLEARED  # fine for anyone
NEVER_USE = NEVER_AUTO
DECISIONS = (*OWNER_CLEARANCES, NEVER_USE)
# The widest film a cleared picture may play in, as the owner picks it.
CLEARANCE_LEVELS = {"anyone": CLEAR_HOLD, "family": "cleared_family", "just-us": "cleared_just_us"}


def clearance_for(level: str) -> str:
    """The decision that clears a picture's hold for this level (`anyone`, `family`, `just-us`)."""
    try:
        return CLEARANCE_LEVELS[level]
    except KeyError:
        raise ValueError(f"unknown level {level!r}: pick anyone, family or just-us") from None


def is_clearance(decision: str | None) -> bool:
    return decision in OWNER_CLEARANCES


def _picture(connection: Connection, asset_id: str, clip_id: str | None) -> list[str]:
    ids = [asset_id]
    if clip_id is None:
        clip_id = connection.execute(
            sa.select(annotation_assets.c.live_photo_video_id).where(
                annotation_assets.c.asset_id == asset_id
            )
        ).scalar()
    if clip_id and clip_id != asset_id:
        ids.append(str(clip_id))
    return ids


def _drop_owner_rows(connection: Connection, ids: list[str]) -> None:
    connection.execute(
        sa.delete(asset_flags).where(
            id_in(connection, asset_flags.c.asset_id, ids), asset_flags.c.source == OWNER_SOURCE
        )
    )


def decide(
    store: Store,
    asset_id: str,
    decision: str,
    *,
    via: str,
    clip_id: str | None = None,
) -> tuple[str, ...]:
    """Record the owner's decision on one picture, replacing any earlier one.

    Returns the ids written: the picture, and its Live Photo clip when there is one. `via`
    names the surface (`web`, `cli`) for the record.
    """
    if decision not in DECISIONS:
        raise ValueError(f"unknown owner decision {decision!r}")
    evidence = json.dumps({"via": via, "at": now()}, sort_keys=True)
    with store.begin() as connection:
        ids = _picture(connection, asset_id, clip_id)
        _drop_owner_rows(connection, ids)
        rows = [
            {
                "asset_id": i,
                "flag": decision,
                "source": OWNER_SOURCE,
                "evidence": evidence,
                "written_at": now_db(),
            }
            for i in ids
        ]
        upsert_rows(connection, asset_flags, rows, keys=("asset_id", "flag", "source"))
        # A concurrent writer on PostgreSQL may have committed another decision since the
        # first delete; the one that commits last is the owner's word.
        connection.execute(
            sa.delete(asset_flags).where(
                id_in(connection, asset_flags.c.asset_id, ids),
                asset_flags.c.source == OWNER_SOURCE,
                asset_flags.c.flag != decision,
            )
        )
    return tuple(ids)


def forget(store: Store, asset_id: str, *, clip_id: str | None = None) -> tuple[str, ...]:
    """Drop the owner's decision on one picture: the app's own holds and rules apply again."""
    with store.begin() as connection:
        ids = _picture(connection, asset_id, clip_id)
        _drop_owner_rows(connection, ids)
    return tuple(ids)


def live_clips(store: Store, asset_ids: Iterable[str]) -> dict[str, str]:
    """The motion clip of each Live Photo among these pictures, as the store banked it."""
    ids = list(dict.fromkeys(asset_ids))
    out: dict[str, str] = {}
    table = annotation_assets
    with store.connect() as connection:
        for chunk in in_chunks(connection, ids):
            rows = connection.execute(
                sa.select(table.c.asset_id, table.c.live_photo_video_id).where(
                    table.c.live_photo_video_id.is_not(None),
                    id_in(connection, table.c.asset_id, chunk),
                )
            )
            out.update({str(a): str(c) for a, c in rows if c})
    return out


def decisions(store: Store, asset_ids: Iterable[str] | None = None) -> dict[str, str]:
    """The owner's decision per picture, for these ids or for every picture that has one."""
    wanted = None if asset_ids is None else set(asset_ids)
    with store.connect() as connection:
        rows = connection.execute(
            sa.select(asset_flags.c.asset_id, asset_flags.c.flag).where(
                asset_flags.c.source == OWNER_SOURCE
            )
        ).all()
    return {
        str(asset_id): str(flag)
        for asset_id, flag in sorted(rows)
        if flag in DECISIONS and (wanted is None or str(asset_id) in wanted)
    }
