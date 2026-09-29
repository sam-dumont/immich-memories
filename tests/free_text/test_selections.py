"""The selections the library computes: firsts, lasts, the farthest trip, an occasion's day."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from immich_memories.config_models_automation import TripsConfig
from immich_memories.free_text.facts import (
    farthest_trip,
    first_pictures,
    last_pictures,
    occasion_day,
)
from immich_memories.free_text.homes import Home
from immich_memories.free_text.library import LibraryPerson, LibraryPicture


def _picture(asset_id: str, day: str, **fields: Any) -> LibraryPicture:
    taken_at = datetime.fromisoformat(day).replace(hour=12, tzinfo=UTC)
    return LibraryPicture(asset_id=asset_id, taken_at=taken_at, media_kind="photo", **fields)


def _kid() -> LibraryPerson:
    return LibraryPerson(
        person_id="kid", name="Sam Example", role="son", birth_date=date(2015, 4, 2)
    )


def test_a_first_picture_is_at_the_onset_and_never_before_the_birth() -> None:
    kid = frozenset({"kid"})
    pictures = [
        _picture("lookalike", "2011-03-10", people=kid),
        _picture("stray", "2015-05-01", people=kid),
        _picture("onset", "2017-01-15", people=kid),
        _picture("after", "2017-02-15", people=kid),
        _picture("later", "2017-04-15", people=kid),
        _picture("latest", "2017-07-15", people=kid),
        _picture("nobody", "2016-06-01"),
    ]

    firsts = first_pictures(pictures, [_kid()])

    assert firsts["kid"].asset_id == "onset"


def test_a_last_picture_is_the_latest_face_and_a_visitor_keeps_the_earliest() -> None:
    visitor = LibraryPerson(person_id="visitor", name="Pat Example", role=None, birth_date=None)
    pictures = [
        _picture("first-visit", "2018-06-01", people=frozenset({"visitor"})),
        _picture("second-visit", "2021-09-01", people=frozenset({"visitor", "kid"})),
        _picture("baby", "2015-05-01", people=frozenset({"kid"})),
    ]

    assert first_pictures(pictures, [visitor])["visitor"].asset_id == "first-visit"
    lasts = last_pictures(pictures, [visitor, _kid()])
    assert {person: picture.asset_id for person, picture in lasts.items()} == {
        "visitor": "second-visit",
        "kid": "second-visit",
    }


def _stay(name: str, first: str, days: int, where: tuple[float, float]) -> list[LibraryPicture]:
    start = date.fromisoformat(first)
    return [
        _picture(
            f"{name}-{n}",
            (start + timedelta(days=n)).isoformat(),
            latitude=where[0],
            longitude=where[1],
        )
        for n in range(days)
    ]


def test_the_farthest_trip_is_measured_from_the_home_of_its_time_by_its_middle_photo() -> None:
    homes = (
        Home(latitude=10.0, longitude=20.0, since=None, until=date(2019, 2, 10)),
        Home(latitude=10.5, longitude=20.5, since=date(2019, 2, 10), until=None),
    )
    # From the later home the early trip would be the farthest (258 km against 208 km), and one
    # wrong fix inside it would win on any single photo. From the home it left from, it is 186.
    early = [
        *_stay("early", "2018-05-01", 4, (8.4, 19.5)),
        *_stay("bad-fix", "2018-05-02", 1, (40.0, 20.0)),
    ]
    late = _stay("late", "2020-08-01", 5, (10.5, 22.4))
    pictures = [*_stay("home", "2018-04-01", 3, (10.0, 20.0)), *early, *late]

    trip = farthest_trip(pictures, homes, TripsConfig())

    assert trip is not None
    assert (trip.first_day, trip.last_day) == (date(2020, 8, 1), date(2020, 8, 5))
    assert trip.asset_ids == frozenset(picture.asset_id for picture in late)
    assert round(trip.distance_km) == 208


US = frozenset({"owner", "partner"})


def test_an_undated_occasion_is_the_day_its_photos_show_its_people_together() -> None:
    pictures = [
        _picture("ours-1", "2016-06-11", caption="A bride and groom at their wedding", people=US),
        _picture("ours-2", "2016-06-11", caption="A wedding cake on a table", people=US),
        _picture("toast", "2016-06-11", caption="Friends raising glasses", people=US),
        *(
            _picture(
                f"guest-{n}",
                "2019-09-20",
                caption="Guests dancing at a wedding",
                people=frozenset({"partner"}),
            )
            for n in range(4)
        ),
    ]

    found = occasion_day(pictures, ["wedding"], US)

    assert found.day == date(2016, 6, 11)
    assert found.photos == 2
    assert "2016-06-11 (2 photos)" in found.reason


def test_no_day_with_its_people_together_is_not_possible_and_says_what_was_found() -> None:
    pictures = [
        _picture(
            "guest", "2019-09-20", caption="Guests at a wedding", people=frozenset({"partner"})
        ),
        _picture("guest-2", "2019-09-20", caption="A wedding arch", people=frozenset()),
        _picture("framed", "2021-01-05", caption="A framed wedding photo", people=frozenset()),
    ]

    found = occasion_day(pictures, ["wedding"], US)

    assert found.day is None
    assert found.reason.startswith("not possible")
    assert found.found == (
        (date(2019, 9, 20), 2, frozenset({"partner"})),
        (date(2021, 1, 5), 1, frozenset()),
    )
