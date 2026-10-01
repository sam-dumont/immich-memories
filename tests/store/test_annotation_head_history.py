"""Old producer versions do not inflate a requested annotation snapshot."""

import tracemalloc

import sqlalchemy as sa

from immich_memories.db import now_db
from immich_memories.db.tables import head_facts
from immich_memories.store.asset_annotations import AssetAnnotationFactRepository


def test_retained_head_versions_do_not_inflate_snapshot_memory(store):
    ids = tuple(f"picture-{i}" for i in range(100))
    stamp = now_db()
    base = {
        "head": "people",
        "label": "one",
        "confidence": 0.9,
        "encoder_key": "fixture",
        "decided_at": stamp,
    }
    with store.begin() as connection:
        connection.execute(
            sa.insert(head_facts),
            [{**base, "asset_id": asset_id, "version": "current"} for asset_id in ids],
        )
    reader = AssetAnnotationFactRepository(
        store,
        description_model=None,
        head_versions={"people": "current"},
        pixel_producer_key="pixel-v1",
    )
    expected = reader.facts_for(ids)

    def peak():
        tracemalloc.start()
        try:
            assert reader.facts_for(ids) == expected
            return tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()

    before = peak()
    with store.begin() as connection:
        connection.execute(
            sa.insert(head_facts),
            [
                {
                    **base,
                    "asset_id": asset_id,
                    "version": f"old-{version}",
                    "label": "outdated " * 30,
                }
                for asset_id in ids
                for version in range(50)
            ],
        )
    assert peak() < before * 3 + 100_000


def test_exact_pairs_and_large_requests_stay_within_backend_bind_limits(store):
    import sqlite3

    ids = tuple(f"picture-{i}" for i in range(1000))
    versions = {f"head-{i}": f"v{i % 4}" for i in range(500)}
    stamp = now_db()
    with store.begin() as connection:
        if store.dialect_name == "sqlite":
            connection.connection.driver_connection.setlimit(
                sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 999
            )
        connection.execute(
            sa.insert(head_facts),
            [
                {
                    "asset_id": ids[0],
                    "head": head,
                    "version": version,
                    "label": label,
                    "confidence": 0.9,
                    "encoder_key": "fixture",
                    "decided_at": stamp,
                }
                for head, version, label in [
                    ("head-0", "v0", "wanted"),
                    ("head-499", "v3", "also wanted"),
                    ("head-0", "v3", "wrong pair"),
                    ("head-499", "v0", "wrong pair"),
                ]
            ],
        )
    reader = AssetAnnotationFactRepository(
        store, description_model=None, head_versions=versions, pixel_producer_key="pixel-v1"
    )
    result = reader.facts_for(ids)
    assert result.requested_asset_ids == ids
    assert not result.unavailable_asset_ids
    assert result.facts[0].heads == (("head-0", "wanted"), ("head-499", "also wanted"))
    assert all(not fact.heads for fact in result.facts[1:])
    empty = AssetAnnotationFactRepository(
        store, description_model=None, head_versions={}, pixel_producer_key="pixel-v1"
    ).facts_for(ids[:1])
    assert empty.facts[0].heads == ()
