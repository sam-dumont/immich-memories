"""The annotation fact repository reads one complete, producer-exact snapshot."""

from __future__ import annotations

import sqlite3
from dataclasses import FrozenInstanceError
from datetime import date
from unittest.mock import patch

import pytest
import sqlalchemy as sa

from tests.annotation_rows import add_rows, annotation_store


def test_description_selection_is_exact_and_preserves_requested_asset_order() -> None:
    from immich_memories.store.asset_annotations import (
        AssetAnnotationFactRepository,
    )

    store = annotation_store()
    add_rows(
        store,
        "descriptions",
        {"asset_id": "asset-b", "model": "wanted-model", "text": "The selected description."},
        {"asset_id": "asset-b", "model": "stale-model", "text": "The stale description."},
    )

    batch = AssetAnnotationFactRepository(
        store,
        description_model="wanted-model",
        head_versions={"activity": "activity-v1"},
        pixel_producer_key="pixel-v1",
    ).facts_for(("asset-b", "asset-a"))

    assert batch.unavailable_asset_ids == ()
    assert tuple(batch.as_mapping()) == ("asset-b", "asset-a")
    assert batch.as_mapping()["asset-b"].description == "The selected description."
    assert batch.as_mapping()["asset-a"].description is None


def test_complete_snapshot_uses_only_the_selected_fact_producers() -> None:
    from immich_memories.store.asset_annotations import (
        AssetAnnotationFactRepository,
        StoredFlagFact,
        StoredMotionBurstFact,
        StoredPersonFact,
        StoredPixelFacts,
    )

    store = annotation_store()
    add_rows(
        store,
        "asset_people",
        {
            "asset_id": "asset-a",
            "person_name": " Zoë  ",
            "person_id": "person-z",
            "birth_date": "2001-02-03",
        },
        {
            "asset_id": "asset-a",
            "person_name": "alex",
            "person_id": "person-a",
            "birth_date": "not-a-date",
        },
    )
    add_rows(
        store,
        "descriptions",
        {"asset_id": "asset-a", "model": "wanted-model", "text": " A  complete description. "},
        {"asset_id": "asset-a", "model": "stale-model", "text": "Stale description."},
    )
    add_rows(
        store,
        "description_fields",
        {
            "asset_id": "asset-a",
            "model": "wanted-model",
            "field": "setting",
            "value": " city  street ",
        },
        {
            "asset_id": "asset-a",
            "model": "wanted-model",
            "field": "exposure",
            "value": "underexposed",
        },
        {
            "asset_id": "asset-a",
            "model": "stale-model",
            "field": "setting",
            "value": "stale setting",
        },
    )
    add_rows(
        store,
        "asset_flags",
        {
            "asset_id": "asset-a",
            "flag": "screen",
            "evidence": '{"reason":"computer display"}',
            "source": "docling",
        },
        {
            "asset_id": "asset-a",
            "flag": "dark",
            "evidence": '{"reason":"low exposure"}',
            "source": "Exposure",
        },
        {
            "asset_id": "asset-a",
            "flag": "review",
            "evidence": '{"reason":"legacy public exposure"}',
            "source": "public-exposure-v2",
        },
    )
    add_rows(
        store,
        "head_facts",
        {
            "asset_id": "asset-a",
            "head": "activity",
            "version": "activity-v1",
            "label": "sport-active",
        },
        {
            "asset_id": "asset-a",
            "head": "activity",
            "version": "activity-v0",
            "label": "stale-label",
        },
        {"asset_id": "asset-a", "head": "venue", "version": "venue-v1", "label": "stadium"},
    )
    # pixel_facts is keyed on asset_id alone: a picture carries one producer's measurement at a
    # time, unlike head_facts where several producer versions can coexist per asset.
    add_rows(
        store,
        "pixel_facts",
        {
            "asset_id": "asset-a",
            "producer_key": "pixel-v1",
            "sharpness": 5.0,
            "brightness": 20.0,
            "contrast": 10.0,
            "dark_fraction": 0.7,
            "bright_fraction": 0.1,
            "needs_rotation": True,
        },
    )
    # pixel_facts_thresholds is keyed on name alone: one current threshold at a time.
    add_rows(
        store,
        "pixel_facts_thresholds",
        {"name": "sharpness_p10", "value": 7.5, "producer_key": "pixel-v1"},
    )
    add_rows(
        store,
        "motion_bursts",
        {
            "asset_id": "asset-a",
            "burst_id": "burst-1",
            "still_ids": '["still-b","still-a"]',
            "duration_seconds": 4.4,
            "beats_a_still": True,
        },
    )

    facts = (
        AssetAnnotationFactRepository(
            store,
            description_model="wanted-model",
            head_versions={"venue": "venue-v1", "activity": "activity-v1"},
            pixel_producer_key="pixel-v1",
        )
        .facts_for(("asset-a",))
        .as_mapping()["asset-a"]
    )

    assert facts.people == (
        StoredPersonFact(person_id="person-a", name="alex", birth_date=None),
        StoredPersonFact(person_id="person-z", name="Zoë", birth_date=date(2001, 2, 3)),
    )
    assert facts.description == "A complete description."
    assert (facts.setting, facts.exposure) == ("city street", "underexposed")
    assert facts.heads == (("activity", "sport-active"), ("venue", "stadium"))
    assert facts.flags == (
        StoredFlagFact(flag="screen", reason="computer display", source="docling"),
    )
    assert facts.pixel == StoredPixelFacts(
        sharpness=5.0,
        brightness=20.0,
        contrast=10.0,
        dark_fraction=0.7,
        bright_fraction=0.1,
        needs_rotation=True,
        soft_below=7.5,
    )
    assert facts.motion == StoredMotionBurstFact(
        burst_id="burst-1",
        still_ids=("still-b", "still-a"),
        duration_seconds=4.4,
        beats_a_still=True,
    )


def test_store_without_legacy_motion_table_remains_a_complete_read() -> None:
    """A picture no motion pass has touched at all has no motion_bursts row, not a missing table."""
    from immich_memories.store.asset_annotations import (
        AssetAnnotationFactRepository,
    )

    store = annotation_store()

    batch = AssetAnnotationFactRepository(
        store,
        description_model="wanted-model",
        head_versions={},
        pixel_producer_key="pixel-v1",
    ).facts_for(("asset-a",))

    assert batch.unavailable_asset_ids == ()
    assert batch.warnings == ()
    assert batch.as_mapping()["asset-a"].motion is None


def test_unreadable_store_fails_open_without_disclosing_requested_ids(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from immich_memories.db import Store
    from immich_memories.db.bootstrap import StoreLocation
    from immich_memories.store.asset_annotations import (
        AssetAnnotationFactRepository,
    )

    private_id = "private-asset-that-must-not-be-logged"
    # WHY: a Store whose engine cannot connect at all -- the boundary a real
    # unreachable database or a permissions failure would present.
    unreachable = Store(
        location=StoreLocation(url="sqlite:////nonexistent-directory/store.db"),
        engine=sa.create_engine("sqlite:////nonexistent-directory/store.db"),
    )
    batch = AssetAnnotationFactRepository(
        unreachable,
        description_model="wanted-model",
        head_versions={},
        pixel_producer_key="pixel-v1",
    ).facts_for((private_id,))

    assert batch.facts == ()
    assert batch.unavailable_asset_ids == (private_id,)
    assert batch.warnings == ("!! annotation fact store unavailable",)
    assert private_id not in caplog.text
    assert private_id not in " ".join(batch.warnings)


def test_a_lifetime_read_stays_under_the_oldest_sqlite_variable_limit() -> None:
    from immich_memories.store.asset_annotations import (
        AssetAnnotationFactRepository,
    )

    store = annotation_store()
    private_ids = tuple(f"private-asset-{index:04d}" for index in range(2000))
    real_connect = sqlite3.connect

    def limited_connect(*args: object, **kwargs: object) -> sqlite3.Connection:
        connection = real_connect(*args, **kwargs)
        # SQLite builds before 3.32 bind at most 999 variables.
        connection.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 999)
        return connection

    # WHY: SQLite is the boundary; its real lowered limit proves every IN list is chunked.
    # SQLAlchemy's pysqlite dialect connects through sqlite3.dbapi2, not sqlite3 itself, and
    # the engine's pool must give up any connection opened before the limit was lowered.
    store.engine.dispose()
    with patch("sqlite3.dbapi2.connect", side_effect=limited_connect):
        batch = AssetAnnotationFactRepository(
            store,
            description_model="wanted-model",
            head_versions={"activity": "activity-v1"},
            pixel_producer_key="pixel-v1",
        ).facts_for(private_ids)
    store.engine.dispose()

    assert batch.unavailable_asset_ids == ()
    assert len(batch.facts) == 2000


def test_returned_fact_records_are_immutable() -> None:
    from immich_memories.store.asset_annotations import (
        AssetAnnotationFactRepository,
    )

    store = annotation_store()
    facts = (
        AssetAnnotationFactRepository(
            store,
            description_model="wanted-model",
            head_versions={},
            pixel_producer_key="pixel-v1",
        )
        .facts_for(("asset-a",))
        .facts[0]
    )

    with pytest.raises(FrozenInstanceError):
        facts.description = "mutated"  # type: ignore[misc]
