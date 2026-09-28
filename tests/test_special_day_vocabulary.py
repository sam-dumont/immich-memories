"""A day is proposed when its own words stand out from its year, not because it matched a list."""

from datetime import date
from types import SimpleNamespace

from immich_memories.analysis.special_day_vocabulary import crowded_out, distinctive_days, telling

RACE = date(2021, 4, 4)


def _year(**extra: list[str]) -> dict[date, list[str]]:
    """Forty ordinary days of cats and bread, and whatever days a test adds."""
    said = {
        date(2021, 1, 1 + n % 28).replace(month=1 + n // 28): [
            "A tabby cat lying on the stairs",
            "Bread rolls on a baking tray",
        ]
        for n in range(40)
    }
    return said | {
        date.fromisoformat(day.replace("_", "-")[1:]): words for day, words in extra.items()
    }


def test_a_day_whose_words_the_year_barely_uses_is_proposed_by_them():
    race = [f"A red Ferrari on the race track, lap {n}" for n in range(12)]
    said = _year(d2021_04_04=race + ["A tabby cat lying on the stairs"] * 3)

    proposed = distinctive_days(said, [RACE, date(2021, 1, 5)])

    assert list(proposed) == [RACE]
    assert "ferrari" in proposed[RACE] and "track" in proposed[RACE]
    assert "cat" not in proposed[RACE]


def test_a_busy_day_of_the_years_usual_words_is_not():
    said = _year(d2021_04_04=["A tabby cat lying on the stairs"] * 60)

    assert distinctive_days(said, [RACE]) == {}


def test_one_rare_word_repeated_is_a_way_of_writing_not_a_day():
    said = _year(d2021_04_04=["A tabby cat lying on the stairs, cute"] * 20)

    assert distinctive_days(said, [RACE]) == {}


def test_forwarded_pictures_count_for_half_and_never_alone():
    sent = [f"Runners in an obstacle race under the arch, {n}" for n in range(12)]
    said = _year(d2021_04_04=["Runners in an obstacle race under the arch"] * 3)

    assert distinctive_days(said, [RACE], forwarded={RACE: sent}) == {}
    assert RACE in distinctive_days(said, [RACE], forwarded={RACE: sent * 2})
    assert distinctive_days(said, [], forwarded={RACE: sent * 2}) == {}


def test_the_pictures_that_say_what_the_year_does_not_are_the_ones_told():
    said = _year()
    pictures = [SimpleNamespace(id=f"p{n}") for n in range(4)]
    captions = {
        "p0": "A tabby cat lying on the stairs",
        "p1": "Runners in an obstacle race under the sponsor arch",
        "p2": "Bread rolls on a baking tray",
        "p3": "A runner crossing the finish line",
    }

    told = telling(pictures, captions, said, keep=2)

    assert [p.id for p in told] == ["p1", "p3"]


def _weeks_of_a_newborn() -> dict[date, list[str]]:
    """Forty days in a row of the same baby, as a newborn's first weeks are written about."""
    first = date(2024, 2, 8)
    return {
        date.fromordinal(first.toordinal() + n): [
            "A baby lying on a blanket",
            "A man holding a baby",
            "A baby sleeping in a crib",
        ]
        * 10
        for n in range(40)
    }


def test_a_crowd_of_confirmed_days_that_say_what_their_weeks_say_is_thinned():
    """A newborn's year (09-28): the reader called 55 ordinary baby days occasions. Each one
    said what the weeks around it said."""
    said = _weeks_of_a_newborn()
    confirmed = sorted(said)[5:25]

    assert crowded_out(confirmed, said) == set(confirmed)


def test_a_day_in_the_crowd_that_shows_what_its_weeks_do_not_stays():
    said = _weeks_of_a_newborn()
    confirmed = sorted(said)[5:25]
    birthday = confirmed[10]
    said[birthday] = ["A child blowing out birthday candles on a cake"] * 12 + said[birthday][:6]

    assert birthday not in crowded_out(confirmed, said)


def test_a_day_alone_is_never_thinned_however_little_stands_out():
    """A pregnancy test is two pictures of an ordinary day; nothing crowds it."""
    said = _weeks_of_a_newborn()
    alone = sorted(said)[20]

    assert crowded_out([alone], said) == set()


def test_a_day_that_stands_out_from_its_year_is_never_thinned():
    said = _weeks_of_a_newborn()
    confirmed = sorted(said)[5:25]

    assert confirmed[3] not in crowded_out(confirmed, said, exempt={confirmed[3]})
