"""The length a memory type asks for before it has seen a picture.

The CLI resolves it here, and the web UI runs the CLI's ``generate`` without a
``--duration`` for an auto-length cut, so this one resolver is the length on
both surfaces.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from immich_memories.memory_types.factory import create_preset
from immich_memories.memory_types.registry import MemoryType
from immich_memories.planning.memory_length import default_duration_for_type
from immich_memories.timeperiod import DateRange


def test_a_full_season_targets_the_date_range_curve_not_a_fixed_135_seconds() -> None:
    summer = create_preset(MemoryType.SEASON, year=2024, season="summer")

    seconds = default_duration_for_type("season", summer.date_ranges[0])

    assert seconds == pytest.approx(195.0, abs=0.1)


# What every dated type asks for, built the way a surface builds it: the preset
# the type's card or flag resolves to, then this resolver on its windows. An
# album has no window until its pictures are fetched, so it has no row.
_DATED_TYPES = {
    MemoryType.YEAR_IN_REVIEW: ({"year": 2024}, 600.0),
    MemoryType.SEASON: ({"year": 2024, "season": "summer"}, 195.0),
    MemoryType.PERSON_SPOTLIGHT: ({"year": 2024, "person_names": ["Riley"]}, 600.0),
    MemoryType.MULTI_PERSON: ({"year": 2024, "person_names": ["Riley", "Bob"]}, 600.0),
    MemoryType.MONTHLY_HIGHLIGHTS: ({"year": 2024, "month": 3}, 60.0),
    MemoryType.ON_THIS_DAY: ({"target_date": date(2024, 6, 15), "years_back": 5}, 45.0),
    MemoryType.HOLIDAY: ({"year": 2024, "holiday": "christmas", "years_back": 5}, 60.0),
    MemoryType.TRIP: (
        {"year": 2024, "trip_start": date(2024, 7, 1), "trip_end": date(2024, 7, 10)},
        130.0,
    ),
    MemoryType.SPECIAL_DAY: (
        {
            "day": date(2016, 6, 12),
            "window": (datetime(2016, 6, 12, 10, 20), datetime(2016, 6, 12, 19, 50)),
        },
        87.0,
    ),
}


def test_every_type_but_album_has_a_length_row() -> None:
    assert set(_DATED_TYPES) == set(MemoryType) - {MemoryType.ALBUM}


@pytest.mark.parametrize(
    ("memory_type", "params", "seconds"),
    [pytest.param(t, p, s, id=str(t)) for t, (p, s) in _DATED_TYPES.items()],
)
def test_a_type_asks_for_its_length_from_its_own_windows(
    memory_type: MemoryType, params: dict, seconds: float
) -> None:
    windows = create_preset(memory_type, **params).date_ranges
    span = DateRange(start=windows[-1].start, end=windows[0].end)

    asked = default_duration_for_type(str(memory_type), span, params, primary_window=windows[0])

    assert asked == pytest.approx(seconds, abs=0.1)
