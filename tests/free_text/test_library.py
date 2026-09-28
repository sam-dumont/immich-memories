"""The library view: what the store holds about each picture, read for a free-text request."""

from __future__ import annotations

from datetime import UTC, date, datetime

from immich_memories.config_models_editorial import EditorialConfig
from immich_memories.free_text.library import read_library
from tests.annotation_rows import add_rows
from tests.people_registry_seed import seed_people

EDITORIAL = EditorialConfig()
PEOPLE = {
    "people": [
        {
            "ids": ["immich-alex", "immich-alex-merged"],
            "name": "Alex Example",
            "birth_date": "2015-04-02",
            "inferred": {"tier": "inner", "evidence": {}},
            "confirmed": {"role": "son", "links": []},
        }
    ]
}


def test_a_picture_carries_what_immich_and_preparation_banked_about_it() -> None:
    store = seed_people(PEOPLE)
    add_rows(
        store,
        "annotation_assets",
        {
            "asset_id": "a1",
            "taken_at": "2021-06-05T10:00:00+00:00",
            "media_kind": "photo",
            "city": "Northvale",
            "state": "Upper Region",
            "country": "Examplia",
            "latitude": 10.5,
            "longitude": 20.25,
        },
    )
    add_rows(
        store,
        "descriptions",
        {"asset_id": "a1", "model": EDITORIAL.description_model, "text": "A black cat asleep"},
    )
    add_rows(
        store,
        "head_facts",
        {
            "asset_id": "a1",
            "head": "doc_docling",
            "version": EDITORIAL.head_versions["doc_docling"],
            "label": "screenshot_from_computer",
        },
    )
    add_rows(
        store,
        "pixel_facts",
        {"asset_id": "a1", "producer_key": EDITORIAL.pixel_producer_key, "sharpness": 41.5},
    )
    add_rows(
        store,
        "asset_people",
        {"asset_id": "a1", "person_name": "Alex Example", "person_id": "immich-alex-merged"},
    )

    view = read_library(store, EDITORIAL)

    (picture,) = view.pictures
    assert picture.asset_id == "a1"
    assert picture.taken_at == datetime(2021, 6, 5, 10, tzinfo=UTC)
    assert picture.caption == "A black cat asleep"
    assert (picture.city, picture.region, picture.country) == (
        "Northvale",
        "Upper Region",
        "Examplia",
    )
    assert (picture.latitude, picture.longitude) == (10.5, 20.25)
    assert picture.media_kind == "photo"
    assert picture.picture_kind == "screenshot_from_computer"
    assert picture.sharpness == 41.5
    assert picture.people == frozenset({"immich-alex"})
    assert view.people["immich-alex"].name == "Alex Example"
    assert view.people["immich-alex"].birth_date == date(2015, 4, 2)


def test_an_unprepared_picture_keeps_its_metadata_and_only_people_file_faces_count() -> None:
    store = seed_people(PEOPLE)
    add_rows(
        store,
        "annotation_assets",
        {"asset_id": "a2", "taken_at": "2022-01-01T08:00:00+00:00", "media_kind": "video"},
    )
    add_rows(
        store,
        "asset_people",
        {"asset_id": "a2", "person_name": "Someone Else", "person_id": "immich-stranger"},
    )

    (picture,) = read_library(store, EDITORIAL).pictures

    assert picture.media_kind == "video"
    assert picture.caption is None
    assert picture.picture_kind is None
    assert picture.sharpness is None
    assert picture.people == frozenset()


def _dated(store, *rows: tuple[str, str]) -> None:
    add_rows(
        store,
        "annotation_assets",
        *({"asset_id": asset_id, "taken_at": taken_at} for asset_id, taken_at in rows),
    )


def test_the_view_holds_the_asked_pictures_oldest_first() -> None:
    store = seed_people(PEOPLE)
    _dated(
        store,
        ("late", "2023-03-01T09:00:00+00:00"),
        ("early", "2019-03-01T09:00:00+00:00"),
        ("elsewhere", "2020-03-01T09:00:00+00:00"),
    )

    everything = read_library(store, EDITORIAL)
    asked = read_library(store, EDITORIAL, asset_ids=["late", "early"])

    assert [p.asset_id for p in everything.pictures] == ["early", "elsewhere", "late"]
    assert [p.asset_id for p in asked.pictures] == ["early", "late"]


def test_the_sharpness_line_is_the_library_tenth_percentile_the_engine_measured() -> None:
    store = seed_people(PEOPLE)
    _dated(store, ("a1", "2021-06-05T10:00:00+00:00"))
    add_rows(
        store,
        "pixel_facts",
        {"asset_id": "a1", "producer_key": EDITORIAL.pixel_producer_key, "sharpness": 12.0},
    )
    add_rows(
        store,
        "pixel_facts_thresholds",
        {"name": "sharpness_p10", "value": 30.0, "producer_key": EDITORIAL.pixel_producer_key},
    )

    assert read_library(store, EDITORIAL).sharpness_line == 30.0


def test_the_owner_is_the_people_file_owner_under_their_first_id() -> None:
    store = seed_people({**PEOPLE, "owner": {"person_id": "immich-alex-merged"}})

    assert read_library(store, EDITORIAL).owner_id == "immich-alex"
    assert read_library(seed_people(PEOPLE), EDITORIAL).owner_id is None
