"""A small candidate set must stay a small read as unrelated banked facts grow.

The work is counted with SQLite's progress handler on the store engine's own connections, so
the schema, indexes and queries are the real ones. SQLite is where the unscoped read regressed
(#1433); PostgreSQL resolves the same id lookups through its primary-key indexes.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from typing import Any

import pytest
import sqlalchemy as sa

from immich_memories.analysis.editorial_description_contract import (
    DESCRIPTION_MODEL,
    DESCRIPTION_SOURCE,
)
from immich_memories.db import Store, now_db
from immich_memories.db.tables.annotations import (
    asset_flags,
    asset_people,
    description_fields,
    descriptions,
    face_boxes,
    face_reads,
    head_facts,
    motion_bursts,
    pixel_facts,
    pixel_facts_thresholds,
)
from immich_memories.store.asset_annotations import AssetAnnotationFactRepository
from immich_memories.store.caption_provenance import origins_for
from immich_memories.store.editorial_preparation import faces_unread, missing_facts

UNRELATED = [f"unrelated-{i}" for i in range(10_000)]


@pytest.fixture
def sqlite_store(store: Store) -> Store:
    if store.dialect_name != "sqlite":
        pytest.skip("counts SQLite virtual-machine steps")
    return store


def bank(store: Store, ids: Iterable[str], model="caption-v1", source="fixture") -> None:
    ids = list(ids)
    now = now_db()
    rows: list[tuple[sa.Table, list[dict[str, Any]]]] = [
        (descriptions, [{"asset_id": a, "model": model, "text": "A person walks.", "source": source, "written_at": now} for a in ids]),
        (description_fields, [{"asset_id": a, "model": model, "field": "setting", "value": "a park", "written_at": now} for a in ids]),
        (head_facts, [{"asset_id": a, "head": "frame_kind", "version": "v1", "label": "people_moment", "confidence": 0.9, "encoder_key": "fixture", "decided_at": now} for a in ids]),
        (pixel_facts, [{"asset_id": a, "producer_key": "pixel-v1", "sharpness": 30, "brightness": 120, "contrast": 40, "dark_fraction": 0, "bright_fraction": 0, "width": 640, "height": 480, "orientation": "landscape", "needs_rotation": False, "computed_at": now} for a in ids]),
        (asset_people, [{"asset_id": a, "person_name": "Person", "person_id": "person-id", "birth_date": None, "written_at": now} for a in ids]),
        (face_boxes, [{"asset_id": a, "ordinal": 0, "named": True, "x1": 0.1, "y1": 0.2, "x2": 0.3, "y2": 0.4, "person_id": "person-id"} for a in ids]),
        (face_reads, [{"asset_id": a, "producer": "immich-faces-v2", "read_at": now} for a in ids]),
        (asset_flags, [{"asset_id": a, "flag": "SOFT", "evidence": "{}", "source": "pixels", "written_at": now} for a in ids]),
        (motion_bursts, [{"asset_id": a, "burst_id": "burst", "still_ids": "[]", "video_ids": "[]", "duration_seconds": 2, "beats_a_still": True, "minimum_seconds": 1, "computed_at": now} for a in ids]),
    ]  # fmt: skip
    with store.begin() as connection:
        for table, values in rows:
            connection.execute(sa.insert(table), values)


@contextmanager
def counted(store: Store) -> Iterator[Callable[[], int]]:
    """Count SQLite steps on every connection the store opens while this is active."""
    steps = 0

    def progress() -> int:
        nonlocal steps
        steps += 100
        return 0

    def instrument(dbapi_connection: Any, _record: Any) -> None:
        dbapi_connection.set_progress_handler(progress, 100)

    # WHY: pooled connections predate the listener; dropping them makes every read reconnect
    # through it, so all queries, indexes and returned facts stay the store's real ones.
    store.engine.dispose()
    sa.event.listen(store.engine, "connect", instrument)
    try:
        yield lambda: steps
    finally:
        sa.event.remove(store.engine, "connect", instrument)
        store.engine.dispose()


def work(store: Store, read: Callable[[], Any]) -> tuple[Any, int]:
    with counted(store) as steps:
        return read(), steps()


def test_missing_facts_work_does_not_grow_with_unrelated_assets(sqlite_store):
    with sqlite_store.begin() as connection:
        connection.execute(
            sa.insert(pixel_facts_thresholds),
            {
                "name": "sharpness_p10",
                "value": 10,
                "producer_key": "pixel-v1",
                "n": 1,
                "computed_at": now_db(),
            },
        )
    bank(sqlite_store, ("selected",))

    def read():
        return missing_facts(
            sqlite_store,
            ("selected", "absent"),
            description_model="caption-v1",
            head_versions={"frame_kind": "v1"},
            pixel_producer_key="pixel-v1",
            preview_for=lambda _: b"",
        )

    before, small_work = work(sqlite_store, read)
    bank(sqlite_store, UNRELATED)
    after, large_work = work(sqlite_store, read)

    assert (
        before
        == after
        == (
            {
                "description:caption-v1": ("absent",),
                "head:frame_kind@v1": ("absent",),
                "pixel:pixel-v1": ("absent",),
            },
            (),
        )
    )
    assert large_work <= small_work * 3 + 1_000


def test_banked_face_checks_ignore_unrelated_pictures(sqlite_store):
    bank(sqlite_store, ("selected",))

    def read():
        return faces_unread(sqlite_store, ("selected", "absent", "absent"))

    before, small_work = work(sqlite_store, read)
    bank(sqlite_store, UNRELATED)
    after, large_work = work(sqlite_store, read)

    assert before == after == ("absent", "absent")
    assert large_work <= small_work * 3 + 1_000


def test_annotation_read_work_depends_on_requested_assets(sqlite_store):
    bank(sqlite_store, ("selected",))
    repository = AssetAnnotationFactRepository(
        sqlite_store,
        description_model="caption-v1",
        head_versions={"frame_kind": "v1"},
        pixel_producer_key="pixel-v1",
    )

    def read():
        return repository.facts_for(("selected", "absent", "selected"))

    before, small_work = work(sqlite_store, read)
    bank(sqlite_store, UNRELATED)
    after, large_work = work(sqlite_store, read)

    assert before == after
    assert after.requested_asset_ids == ("selected", "absent")
    assert not after.unavailable_asset_ids
    selected = after.as_mapping()["selected"]
    assert selected.description == "A person walks."
    assert selected.heads == (("frame_kind", "people_moment"),)
    assert (
        selected.people and selected.faces and selected.flags and selected.pixel and selected.motion
    )
    assert large_work <= small_work * 3 + 1_000


def test_caption_reuse_and_origins_ignore_unrelated_banked_captions(sqlite_store):
    bank(sqlite_store, ("selected",), DESCRIPTION_MODEL, DESCRIPTION_SOURCE)

    def read():
        return origins_for(sqlite_store, ("selected", "absent"), "llm-caption-v1@fixture")

    before, small_work = work(sqlite_store, read)
    bank(sqlite_store, UNRELATED, DESCRIPTION_MODEL, DESCRIPTION_SOURCE)
    after, large_work = work(sqlite_store, read)

    assert before == after
    assert sorted((r["status"], r["assets"]) for r in after["origins"]) == [
        ("none", 1),
        ("unknown", 1),
    ]
    assert large_work <= small_work * 3 + 1_000
