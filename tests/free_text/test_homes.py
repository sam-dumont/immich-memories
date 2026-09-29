"""Where the owner lived, and when, read from where the library's pictures were taken."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from immich_memories.free_text.homes import Home, homes_over_time
from immich_memories.free_text.library import LibraryPicture

OLD_HOME = (10.0, 20.0)
NEW_HOME = (10.5, 20.5)


def _days_at(where: tuple[float, float], first: date, count: int) -> list[LibraryPicture]:
    return [
        LibraryPicture(
            asset_id=f"{first.isoformat()}-{n}",
            taken_at=datetime.combine(first + timedelta(days=9 * n), datetime.min.time(), UTC),
            media_kind="photo",
            latitude=where[0],
            longitude=where[1],
        )
        for n in range(count)
    ]


def test_a_move_starts_a_new_home_on_the_first_day_pictured_there() -> None:
    pictures = [
        *_days_at(OLD_HOME, date(2017, 1, 3), 30),
        *_days_at(OLD_HOME, date(2018, 1, 3), 30),
        *_days_at(NEW_HOME, date(2019, 2, 10), 30),
        *_days_at(NEW_HOME, date(2020, 1, 3), 30),
    ]

    homes = homes_over_time(pictures)

    assert homes == (
        Home(latitude=10.0, longitude=20.0, since=None, until=date(2019, 2, 10)),
        Home(latitude=10.5, longitude=20.5, since=date(2019, 2, 10), until=None),
    )


def test_a_library_without_a_settled_place_falls_back_to_the_home_base() -> None:
    fortnight_away = _days_at(OLD_HOME, date(2019, 7, 1), 5)

    assert homes_over_time(fortnight_away, configured=NEW_HOME) == (
        Home(latitude=10.5, longitude=20.5, since=None, until=None),
    )
    assert homes_over_time(fortnight_away) == ()
