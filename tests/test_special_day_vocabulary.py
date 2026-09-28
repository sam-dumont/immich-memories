"""A day is proposed when its own words stand out from its year, not because it matched a list."""

from datetime import date
from types import SimpleNamespace

from immich_memories.analysis.special_day_vocabulary import distinctive_days, telling

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
