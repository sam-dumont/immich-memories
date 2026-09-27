"""A small candidate set must stay a small read as unrelated banked facts grow."""

import sqlite3

from immich_memories.analysis.editorial_description_contract import (
    DESCRIPTION_MODEL,
    DESCRIPTION_SOURCE,
)
from immich_memories.store.asset_annotations import AssetAnnotationFactRepository
from immich_memories.store.caption_provenance import origins_for
from immich_memories.store.editorial_preparation import faces_unread, initialize, missing_facts


def bank(connection, ids, model="caption-v1", source="fixture"):
    connection.executemany(
        "INSERT INTO descriptions VALUES (?, ?, 'A person walks.', ?, 'now')",
        ((asset, model, source) for asset in ids),
    )
    connection.executemany(
        "INSERT INTO description_fields VALUES (?, ?, 'setting', 'a park', 'now')",
        ((asset, model) for asset in ids),
    )
    connection.executemany(
        "INSERT INTO head_facts VALUES (?, 'frame_kind', 'v1', 'people_moment', 0.9, 'fixture', 'now')",
        ((asset,) for asset in ids),
    )
    connection.executemany(
        "INSERT INTO pixel_facts VALUES (?, 'pixel-v1', 30, 120, 40, 0, 0, 640, 480, 'landscape', 0, 'now')",
        ((asset,) for asset in ids),
    )
    for statement in (
        "INSERT INTO asset_people VALUES (?, 'Person', 'person-id', NULL, 'now')",
        "INSERT INTO face_boxes VALUES (?, 1, 0.1, 0.2, 0.3, 0.4, 'person-id')",
        "INSERT INTO face_reads VALUES (?, 'immich-faces-v2', 'now')",
        "INSERT INTO flags VALUES (?, 'SOFT', '{}', 'pixels', 'now')",
        "INSERT INTO motion_bursts VALUES (?, 'burst', '[]', '[]', 2, 1, 1, 'now')",
    ):
        connection.executemany(statement, ((asset,) for asset in ids))


def database_work(connection, read):
    steps = 0

    def progress():
        nonlocal steps
        steps += 100
        return 0

    connection.set_progress_handler(progress, 100)
    try:
        return read(), steps
    finally:
        connection.set_progress_handler(None, 0)


def test_missing_facts_work_does_not_grow_with_unrelated_assets():
    with sqlite3.connect(":memory:") as connection:
        initialize(connection)
        connection.execute(
            "INSERT INTO pixel_facts_thresholds VALUES ('sharpness_p10', 10, 'pixel-v1', 1, 'now')"
        )
        bank(connection, ("selected",))

        def read():
            return missing_facts(
                connection,
                ("selected", "absent"),
                description_model="caption-v1",
                head_versions={"frame_kind": "v1"},
                pixel_producer_key="pixel-v1",
                preview_for=lambda _: b"",
            )

        before, small_work = database_work(connection, read)
        bank(connection, [f"unrelated-{i}" for i in range(10_000)])
        after, large_work = database_work(connection, read)

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


def test_banked_face_checks_ignore_unrelated_pictures():
    with sqlite3.connect(":memory:") as connection:
        initialize(connection)
        bank(connection, ("selected",))

        def read():
            return faces_unread(connection, ("selected", "absent", "absent"))

        before, small_work = database_work(connection, read)
        bank(connection, [f"unrelated-{i}" for i in range(10_000)])
        after, large_work = database_work(connection, read)

    assert before == after == ("absent", "absent")
    assert large_work <= small_work * 3 + 1_000


def test_annotation_read_work_depends_on_requested_assets(tmp_path, monkeypatch):
    path = tmp_path / "annotations.sqlite"
    with sqlite3.connect(path) as connection:
        initialize(connection)
        bank(connection, ("selected",))

    steps = 0
    connect = sqlite3.connect

    def progress():
        nonlocal steps
        steps += 100
        return 0

    def instrumented_connect(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connection.set_progress_handler(progress, 100)
        return connection

    # WHY: attach a work counter to the repository's real SQLite connection;
    # all schema, queries, indexes and returned facts remain real.
    monkeypatch.setattr(sqlite3, "connect", instrumented_connect)
    repository = AssetAnnotationFactRepository(
        path,
        description_model="caption-v1",
        head_versions={"frame_kind": "v1"},
        pixel_producer_key="pixel-v1",
    )
    before = repository.facts_for(("selected", "absent", "selected"))
    small_work = steps
    with connect(path) as connection:
        bank(connection, [f"unrelated-{i}" for i in range(10_000)])
    steps = 0
    after = repository.facts_for(("selected", "absent", "selected"))

    assert before == after
    assert after.requested_asset_ids == ("selected", "absent")
    assert not after.unavailable_asset_ids
    selected = after.as_mapping()["selected"]
    assert selected.description == "A person walks."
    assert selected.heads == (("frame_kind", "people_moment"),)
    assert (
        selected.people and selected.faces and selected.flags and selected.pixel and selected.motion
    )
    assert steps <= small_work * 3 + 1_000


def test_caption_reuse_and_origins_ignore_unrelated_banked_captions():
    with sqlite3.connect(":memory:") as connection:
        initialize(connection)
        bank(connection, ("selected",), DESCRIPTION_MODEL, DESCRIPTION_SOURCE)

        def read():
            return origins_for(connection, ("selected", "absent"), "llm-caption-v1@fixture")

        before, small_work = database_work(connection, read)
        bank(
            connection,
            [f"unrelated-{i}" for i in range(10_000)],
            DESCRIPTION_MODEL,
            DESCRIPTION_SOURCE,
        )
        after, large_work = database_work(connection, read)

    assert before == after
    assert sorted((r["status"], r["assets"]) for r in after["origins"]) == [
        ("none", 1),
        ("unknown", 1),
    ]
    assert large_work <= small_work * 3 + 1_000
