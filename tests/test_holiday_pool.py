"""A holiday film is made of the holiday: each year's day leads, its days around only fill in.

The automatic Assumption film read 13 to 17 August in every year; its pool was mostly the busy
days around the 15th, and 2 of its 12 shots were from the holiday itself.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from immich_memories.memory_types.date_builders import build_holiday
from immich_memories.memory_types.holiday_pool import keep_the_day

# Pictures per day on 13, 14, 15, 16 and 17 August, in the shape of the library that made it.
AUGUST = {
    2008: (59, 74, 0, 0, 4),
    2021: (26, 135, 4, 8, 12),
    2022: (243, 5, 99, 10, 16),
    2024: (205, 126, 174, 32, 43),
    2026: (23, 26, 71, 18, 15),
}


def _pictures(per_year=AUGUST, hour=14):
    return [
        datetime(year, 8, 13 + offset, hour) + timedelta(minutes=n)
        for year, counts in per_year.items()
        for offset, count in enumerate(counts)
        for n in range(count)
    ]


def _kept(photos, videos=()):
    windows = build_holiday("08-15", 2026)
    kept_videos, kept_photos = keep_the_day([list(videos), photos], windows, taken=lambda t: t)
    return kept_videos, kept_photos


def _per_day(pictures):
    counts: dict[date, int] = {}
    for taken in pictures:
        counts[taken.date()] = counts.get(taken.date(), 0) + 1
    return counts


def test_a_year_that_kept_the_day_keeps_only_the_day():
    _, kept = _kept(_pictures())

    per_day = _per_day(kept)
    assert per_day[date(2022, 8, 15)] == 99
    assert per_day[date(2024, 8, 15)] == 174
    assert per_day[date(2026, 8, 15)] == 71
    assert date(2022, 8, 13) not in per_day
    assert date(2024, 8, 14) not in per_day


def test_a_thin_day_is_filled_in_from_the_days_around_it():
    _, kept = _kept(_pictures())

    per_day = _per_day(kept)
    # Four pictures on the 15th of 2021: the rest of the window joins them.
    assert per_day[date(2021, 8, 15)] == 4
    assert per_day[date(2021, 8, 14)] == 135


def test_a_year_with_nothing_on_the_day_adds_nothing():
    _, kept = _kept(_pictures())

    assert not any(taken.year == 2008 for taken in kept)


def test_the_night_that_started_on_the_day_belongs_to_it():
    party = [datetime(2024, 8, 15, 22, 0), datetime(2024, 8, 16, 1, 30)]
    morning_after = [datetime(2024, 8, 16, 10, 0)]
    day = [datetime(2024, 8, 15, 12, minute) for minute in range(10)]

    _, kept = _kept([*day, *party, *morning_after])

    assert datetime(2024, 8, 16, 1, 30) in kept
    assert datetime(2024, 8, 16, 10, 0) not in kept


def test_videos_and_photos_count_together_for_a_thin_day():
    photos = [datetime(2024, 8, 15, 12, n) for n in range(3)] + [datetime(2024, 8, 14, 12, 0)]
    videos = [datetime(2024, 8, 15, 13, n) for n in range(3)]

    kept_videos, kept_photos = _kept(photos, videos)

    assert len(kept_videos) == 3
    # Six on the day is not thin: the 14th stays out.
    assert datetime(2024, 8, 14, 12, 0) not in kept_photos


def test_generate_narrows_a_holiday_pool_on_each_pictures_own_clock():
    from datetime import UTC

    from immich_memories.cli._asset_fetch import holiday_pool
    from tests.conftest import make_asset

    def asset(asset_id, utc, local):
        made = make_asset(asset_id, file_created_at=utc)
        return made.model_copy(update={"local_date_time": local})

    windows = build_holiday("08-15", 2024, years_back=1)
    # 23:30 on the 14th in UTC is 01:30 on the 15th where the party was.
    party = asset("party", datetime(2024, 8, 14, 23, 30, tzinfo=UTC), datetime(2024, 8, 15, 1, 30))
    day = [
        asset(f"day-{n}", datetime(2024, 8, 15, 10, n, tzinfo=UTC), datetime(2024, 8, 15, 12, n))
        for n in range(5)
    ]
    before = asset("before", datetime(2024, 8, 13, 10, tzinfo=UTC), datetime(2024, 8, 13, 12))

    videos, photos = holiday_pool("holiday", [party, before], day, windows)

    assert [v.id for v in videos] == ["party"]
    assert len(photos) == 5
    assert holiday_pool("on_this_day", [party, before], day, windows) == ([party, before], day)
