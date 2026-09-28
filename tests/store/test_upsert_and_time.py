"""The two portable helpers every repository uses: upsert and naive-UTC time."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from immich_memories.db import from_db, iso_from_db, to_db, upsert
from immich_memories.db.tables import store_meta

WHEN = datetime(2026, 9, 27, 12, 30, 15, 123456)


def _rows(store) -> dict[str, object]:
    with store.connect() as connection:
        return dict(connection.execute(sa.select(store_meta.c.key, store_meta.c.value)).all())


def test_upsert_inserts_then_updates_by_key(store):
    with store.begin() as connection:
        upsert(
            connection,
            store_meta,
            [
                {"key": "a", "value": 1, "updated_at": WHEN},
                {"key": "b", "value": 2, "updated_at": WHEN},
            ],
            keys=["key"],
        )
    with store.begin() as connection:
        upsert(
            connection, store_meta, [{"key": "a", "value": 10, "updated_at": WHEN}], keys=["key"]
        )

    assert _rows(store) == {"a": 10, "b": 2}


def test_upsert_updates_only_the_named_columns(store):
    later = WHEN + timedelta(days=1)
    with store.begin() as connection:
        upsert(connection, store_meta, [{"key": "a", "value": 1, "updated_at": WHEN}], keys=["key"])
        upsert(
            connection,
            store_meta,
            [{"key": "a", "value": 2, "updated_at": later}],
            keys=["key"],
            update=["updated_at"],
        )

    with store.connect() as connection:
        row = connection.execute(sa.select(store_meta)).one()
    assert (row.value, row.updated_at) == (1, later)


def test_an_empty_update_keeps_the_first_write(store):
    with store.begin() as connection:
        upsert(connection, store_meta, [{"key": "a", "value": 1, "updated_at": WHEN}], keys=["key"])
        upsert(
            connection,
            store_meta,
            [{"key": "a", "value": 2, "updated_at": WHEN}],
            keys=["key"],
            update=(),
        )

    assert _rows(store) == {"a": 1}


def test_upserting_nothing_is_a_no_op(store):
    with store.begin() as connection:
        upsert(connection, store_meta, [], keys=["key"])

    assert _rows(store) == {}


@pytest.mark.parametrize(
    "given",
    [
        "2026-09-27T14:30:15.123456+02:00",
        "2026-09-27T12:30:15.123456Z",
        datetime(2026, 9, 27, 7, 30, 15, 123456, tzinfo=timezone(timedelta(hours=-5))),
        WHEN,
    ],
)
def test_any_instant_goes_in_as_naive_utc(given):
    assert to_db(given) == WHEN


def test_time_round_trips_through_both_backends_to_the_microsecond(store):
    instant = datetime(2026, 9, 27, 14, 30, 15, 123456, tzinfo=timezone(timedelta(hours=2)))
    with store.begin() as connection:
        connection.execute(
            store_meta.insert(), {"key": "t", "value": {}, "updated_at": to_db(instant)}
        )
    with store.connect() as connection:
        stored = connection.execute(sa.select(store_meta.c.updated_at)).scalar_one()

    assert from_db(stored) == instant
    assert from_db(stored).tzinfo is UTC
    assert iso_from_db(stored) == "2026-09-27T12:30:15.123456+00:00"


def test_nothing_stays_nothing():
    assert to_db(None) is None
    assert from_db(None) is None
    assert iso_from_db(None) is None
