"""The v1 detector bank: preserve compatible answers and migrate proven equivalents."""

from __future__ import annotations

from collections.abc import Mapping

import sqlalchemy as sa

from immich_memories.analysis.editorial_preparation_detectors import (
    MARQO_HEAD,
    MARQO_ONNX_ID,
    MARQO_STILL_EQUIVALENT,
    MARQO_VERSION,
)
from immich_memories.db import Store
from immich_memories.db.tables import annotation_assets, head_facts
from immich_memories.store.batches import upsert_rows

CONTRACT = "detector-facts-v1"


def _valid(table):
    return sa.and_(
        sa.func.trim(table.c.label) != "", table.c.confidence >= 0, table.c.confidence <= 1
    )


def _current_exists(versions: Mapping[str, str]):
    newer = head_facts.alias("current_fact")
    return (
        sa.select(newer.c.asset_id)
        .where(
            newer.c.asset_id == head_facts.c.asset_id,
            newer.c.head == head_facts.c.head,
            sa.or_(
                *(sa.and_(newer.c.head == h, newer.c.version == v) for h, v in versions.items())
            ),
        )
        .correlate(head_facts)
        .exists()
    )


def _migratable():
    h = head_facts
    return sa.and_(
        h.c.head == MARQO_HEAD,
        h.c.version == MARQO_STILL_EQUIVALENT,
        h.c.encoder_key == MARQO_ONNX_ID,
        _valid(h),
        annotation_assets.c.media_kind == "photo",
        ~_current_exists({MARQO_HEAD: MARQO_VERSION}),
    )


def _source():
    return head_facts.outerjoin(
        annotation_assets, head_facts.c.asset_id == annotation_assets.c.asset_id
    )


def fact_status(store: Store, versions: Mapping[str, str]) -> list[dict]:
    """Count compatible, superseded, migratable and stale rows without loading models."""
    h = head_facts
    current = sa.or_(
        *(sa.and_(h.c.head == key, h.c.version == version) for key, version in versions.items())
    )
    state = sa.case(
        (~h.c.head.in_(list(versions)), "unrecognized"),
        (sa.and_(current, _valid(h)), "reusable"),
        (sa.and_(~current, _current_exists(versions)), "superseded"),
        (_migratable() if versions.get(MARQO_HEAD) == MARQO_VERSION else sa.false(), "migrate"),
        else_="refresh",
    ).label("state")
    with store.connect() as connection:
        rows = connection.execute(
            sa.select(h.c.head, h.c.version, sa.func.count().label("facts"), state)
            .select_from(_source())
            .group_by(h.c.head, h.c.version, state)
            .order_by(h.c.head, h.c.version, state)
        )
        return [dict(row._mapping) for row in rows]


def migrate_facts(store: Store, *, apply: bool = False) -> dict:
    """Copy verified still-image equivalents, retaining old versions and newer answers."""
    count = 0
    sample: list[str] = []
    with store.begin() if apply else store.connect() as connection:
        rows = connection.execute(
            sa.select(head_facts)
            .select_from(_source())
            .where(_migratable())
            .order_by(head_facts.c.asset_id)
        )
        for batch in rows.partitions(256):
            count += len(batch)
            sample.extend(row.asset_id for row in batch[: max(0, 20 - len(sample))])
            if apply:
                upsert_rows(
                    connection,
                    head_facts,
                    [{**row._mapping, "version": MARQO_VERSION} for row in batch],
                    keys=("asset_id", "head", "version"),
                    update=(),
                )
    return {
        "contract": CONTRACT,
        "head": MARQO_HEAD,
        "from": MARQO_STILL_EQUIVALENT,
        "to": MARQO_VERSION,
        "eligible": count,
        "applied": apply,
        "asset_ids": sample,
        "sample_limit": 20,
    }


def refresh_facts(
    store: Store, *, heads: tuple[str, ...], asset_ids: tuple[str, ...], apply: bool = False
) -> dict:
    """Forget only the named detector answers; preparation resumes missing work later.

    Remove every version of the selected head so compatible older rows cannot be
    carried forward again when the owner explicitly asks for fresh inference.
    """
    from immich_memories.store.batches import id_in, in_chunks

    if not heads or not asset_ids:
        raise ValueError("Refresh requires both heads and asset IDs")
    count = 0
    h = head_facts
    with store.begin() if apply else store.connect() as connection:
        for chunk in in_chunks(connection, list(dict.fromkeys(asset_ids))):
            selected = sa.and_(h.c.head.in_(heads), id_in(connection, h.c.asset_id, chunk))
            count += (
                connection.scalar(sa.select(sa.func.count()).select_from(h).where(selected)) or 0
            )
            if apply:
                connection.execute(sa.delete(h).where(selected))
    return {
        "contract": CONTRACT,
        "heads": sorted(set(heads)),
        "asset_ids": sorted(set(asset_ids)),
        "facts": count,
        "applied": apply,
    }
