"""A holiday falls where the home base's country keeps it.

A country's public holidays come from the `holidays` library; a few family days no public calendar
lists (Mother's Day, Father's Day, Valentine's, Halloween, the two eves) are added on top. The list
used to be US dates everywhere, so a Belgian library's Father's Day was the week after its own.
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


def test_discovery_skips_the_holidays_the_home_country_keeps():
    """The race on the American Father's Day was skipped as a holiday a Belgian family keeps."""
    from immich_memories.automation.special_day_scan import holidays_in

    belgian = holidays_in(2023, country="BE")

    assert belgian[date(2023, 6, 11)] == "Father's Day"
    assert date(2023, 6, 18) not in belgian
    assert "Thanksgiving" not in belgian.values()


def test_a_year_holds_its_country_s_public_holidays_and_the_family_days():
    from immich_memories.memory_types.date_builders import holidays_of

    belgian = holidays_of(2023, "BE")

    assert belgian[date(2023, 7, 21)] == "National Day"
    assert belgian[date(2023, 5, 18)] == "Ascension Day"
    assert belgian[date(2023, 6, 11)] == "Father's Day"
    assert belgian[date(2023, 2, 14)] == "Valentine's Day"
    assert "Thanksgiving" not in " ".join(belgian.values())


def test_a_public_holiday_resolves_by_its_name_in_its_country():
    assert resolve_holiday("ascension day", 2023, country="BE") == date(2023, 5, 18)
    with pytest.raises(ValueError, match="not kept in DE"):
        resolve_holiday("national day", 2023, country="DE")


@pytest.mark.parametrize(
    "name,code",
    [("Belgium", "BE"), ("United States", "US"), ("The Netherlands", "NL"), ("Atlantis", None)],
)
def test_a_country_immich_names_is_read_as_its_code(name, code):
    from immich_memories.home_country import country_code

    assert country_code(name) == code


def test_the_home_base_decides_the_country(monkeypatch):
    import httpx

    from immich_memories.config_loader import Config
    from immich_memories.home_country import home_country

    seen = []

    # WHY: Immich's reverse geocode is the boundary; it answers from the server's own geodata.
    def reverse(url, *, params, **_kwargs):
        seen.append((url, params))
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json=[{"country": "Belgium", "city": "Brussels"}],
        )

    monkeypatch.setattr(httpx, "get", reverse)
    config = Config(
        immich={"url": "http://immich.test", "api_key": "k"},
        trips={"homebase_latitude": 50.85, "homebase_longitude": 4.35},
    )

    assert home_country(config) == "BE"
    assert seen == [("http://immich.test/api/map/reverse-geocode", {"lat": 50.85, "lon": 4.35})]


def test_without_a_home_base_the_country_is_the_one_it_always_was():
    from immich_memories.config_loader import Config
    from immich_memories.home_country import home_country

    assert home_country(Config()) == "US"
