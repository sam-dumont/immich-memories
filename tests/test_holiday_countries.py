"""A family holiday falls on the date the family's country keeps it.

Mother's Day, Father's Day and Thanksgiving move by country. The list kept the US dates, so a
Belgian library's Father's Day was the week after its own, and a cycling race on the American one
was skipped as a holiday spent at home.
"""

from datetime import date

import pytest

from immich_memories.memory_types.date_builders import resolve_holiday


@pytest.mark.parametrize(
    "holiday,country,expected",
    [
        ("fathers_day", "US", date(2023, 6, 18)),
        ("fathers_day", "BE", date(2023, 6, 11)),
        ("fathers_day", "DE", date(2023, 5, 18)),  # Ascension Day
        ("fathers_day", "IT", date(2023, 3, 19)),
        ("fathers_day", "AU", date(2023, 9, 3)),
        ("mothers_day", "US", date(2023, 5, 14)),
        ("mothers_day", "BE", date(2023, 5, 14)),
        ("mothers_day", "GB", date(2023, 3, 19)),  # three weeks before Easter
        ("mothers_day", "ES", date(2023, 5, 7)),
        ("mothers_day", "FR", date(2023, 6, 4)),  # the last Sunday of May was Pentecost
        ("mothers_day", "FR", date(2024, 5, 26)),
        ("thanksgiving", "US", date(2023, 11, 23)),
        ("thanksgiving", "CA", date(2023, 10, 9)),
    ],
)
def test_a_family_holiday_falls_where_the_country_keeps_it(holiday, country, expected):
    assert resolve_holiday(holiday, expected.year, country=country) == expected


def test_a_country_that_does_not_keep_a_holiday_says_so():
    with pytest.raises(ValueError, match="not kept in BE"):
        resolve_holiday("thanksgiving", 2023, country="BE")


def test_without_a_country_the_dates_are_the_ones_they_always_were():
    assert resolve_holiday("fathers_day", 2023) == date(2023, 6, 18)
    assert resolve_holiday("christmas", 2023, country="be") == date(2023, 12, 25)


def test_discovery_skips_the_holidays_the_library_s_country_keeps():
    """The race on the American Father's Day was skipped as a holiday a Belgian family keeps."""
    from immich_memories.automation.special_day_scan import holidays_in

    belgian = holidays_in(2023, country="BE")

    assert belgian[date(2023, 6, 11)] == "Father's Day"
    assert date(2023, 6, 18) not in belgian
    assert "Thanksgiving" not in belgian.values()
