"""A story is named in the film's language, the summary built from it too.

A French birthday film was summarised as "Orchardville, 31 August – 1 September, puis
Saturday 13 September": the names were English, the joining word French. Every name the rules
write (days, spans, days at home, days out, trips, legs, birthdays, visits) comes from the
film language's own catalogue and CLDR's own month and weekday names.
"""

from __future__ import annotations

from collections import Counter

import pytest

from immich_memories.analysis.stories.names import (
    day_label,
    home_name,
    leg_name,
    outing_name,
    span_label,
    trip_name,
    trip_purpose,
)
from immich_memories.analysis.stories.occasions import find_occasions, spoken_list
from immich_memories.analysis.structure.film_summary import plain_summary
from immich_memories.i18n import SUPPORTED_LOCALES, film_texts

_STORY_KEYS = {
    "story.weekday_date",
    "story.span_same_month",
    "story.span",
    "story.place_when",
    "story.home_day_purpose",
    "story.home_days",
    "story.home_days_purpose",
    "story.day_out",
    "story.days_out",
    "story.head_when",
    "story.across",
    "story.more_places",
    "story.trip_to",
    "story.trip_away",
    "story.leg",
    "story.days_away",
    "story.from_to",
    "story.in_place",
    "story.birthday",
    "story.turns",
    "story.visit",
    "story.comes_over",
}
# Words only the English names use: none may reach a film in another language.
_ENGLISH = (
    "Days at home",
    "Ordinary",
    "A day",
    "Days out",
    "Trip to",
    "birthday",
    "visit",
    "July",
    "Saturday",
    " to ",
)


def test_a_french_film_names_its_days_in_french() -> None:
    assert day_label("2025-09-13", "fr") == "samedi 13 septembre"
    assert home_name(["2025-09-13"], ["Pooltown"], "fr")[0] == "Pooltown, samedi 13 septembre"
    # A name that opens on the day starts with a capital, as a name does.
    assert home_name(["2025-09-13"], ["Pooltown", "Seaside"], "fr")[0] == "Samedi 13 septembre"
    assert span_label("2025-08-31", "2025-09-01", "fr") == "31 août – 1 septembre"
    assert home_name(["2026-09-02", "2026-09-06"], [], "fr")[0] == (
        "Jours à la maison, 2–6 septembre"
    )
    assert outing_name(["2025-08-31", "2025-09-01"], ["Orchardville"], "fr")[0] == (
        "Orchardville, 31 août – 1 septembre"
    )
    assert trip_name(album=None, farthest="Nordkapp", locale="fr") == "Voyage à Nordkapp"
    assert leg_name(["Copenhague", "Nordkapp"], trip="Nord", legs=2, locale="fr") == (
        "De Copenhague à Nordkapp"
    )


def test_a_german_and_a_japanese_film_write_dates_their_own_way() -> None:
    assert day_label("2025-07-06", "de") == "Sonntag, 6. Juli"
    assert span_label("2025-07-01", "2025-07-04", "de") == "1.–4. Juli"
    assert day_label("2025-07-06", "ja") == "7月6日日曜日"


def test_the_english_names_are_unchanged() -> None:
    assert day_label("2025-07-06", "en") == "Sunday 6 July"
    assert span_label("2025-06-30", "2025-07-02", "en") == "30 June – 2 July"
    assert trip_purpose(["2025-07-12", "2025-07-30"], ["Copenhagen", "Kristiansand"], "en") == (
        "19 days away, Copenhagen to Kristiansand"
    )


def test_a_birthday_and_a_visit_are_named_in_the_films_language() -> None:
    found = find_occasions(
        {"2025-07-05": Counter({"Kit": 3}), "2025-07-07": Counter({"Pat": 3, "Lou": 3})},
        relation_of={"Kit": "child", "Pat": "parent", "Lou": "parent"},
        birth_dates={"Kit": "2020-07-05"},
        close_family=frozenset({"Kit", "Pat", "Lou"}),
        locale="fr",
    )

    assert (found["2025-07-05"].name, found["2025-07-05"].purpose) == (
        "Anniversaire de Kit",
        "Kit a 5 ans",
    )
    assert (found["2025-07-07"].name, found["2025-07-07"].purpose) == (
        "Visite de Lou et Pat",
        "Lou et Pat passent",
    )
    assert spoken_list(["Pat", "Lou", "Remy"], "fr") == "Pat, Lou et Remy"


def test_the_plain_summary_of_a_french_film_is_french_throughout() -> None:
    stories = [
        {
            "key": "S1",
            "weight": "major",
            "title": home_name(["2025-09-13"], ["Pooltown"], "fr")[0],
            "days": ["2025-09-13"],
        },
        {
            "key": "S2",
            "weight": "major",
            "title": outing_name(["2025-08-31", "2025-09-01"], ["Orchardville"], "fr")[0],
            "days": ["2025-08-31"],
        },
    ]

    assert plain_summary(stories, "fr") == (
        "Orchardville, 31 août – 1 septembre, puis Pooltown, samedi 13 septembre"
    )


@pytest.mark.parametrize("locale", SUPPORTED_LOCALES)
def test_every_language_writes_every_story_name_itself(locale: str) -> None:
    assert set(film_texts(locale)) >= _STORY_KEYS, sorted(_STORY_KEYS - set(film_texts(locale)))
    if locale == "en":
        return
    names = [
        day_label("2025-07-05", locale),
        span_label("2025-06-30", "2025-07-01", locale),
        *home_name(["2025-07-02", "2025-07-06"], ["Pooltown", "Seaside"], locale),
        *home_name(["2025-07-05"], ["Pooltown"], locale),
        *outing_name(["2025-07-05"], ["Pooltown"], locale),
        *outing_name(["2025-07-05", "2025-07-06"], [], locale),
        trip_name(album=None, farthest="Nordkapp", locale=locale),
        trip_name(album=None, farthest=None, locale=locale),
        leg_name(["Oslo", "Bergen"], trip="North", legs=2, locale=locale),
        trip_purpose(["2025-07-05", "2025-07-12"], ["Oslo", "Bergen"], locale),
        trip_purpose(["2025-07-05"], ["Oslo"], locale),
    ]
    for name in names:
        assert not [word for word in _ENGLISH if word in name], (locale, name)


def test_a_span_across_years_names_its_years_and_a_day_is_never_a_range() -> None:
    """A holiday film named a story "Days at home, 15 August – 15 August" (2004 and 2022)."""
    assert span_label("2004-08-15", "2022-08-15", "en") == "15 August 2004 – 15 August 2022"
    assert home_name(["2004-08-15", "2022-08-15"], [], "fr")[0] == (
        "Jours à la maison, 15 août 2004 – 15 août 2022"
    )
    assert span_label("2025-08-15", "2025-08-15", "en") == "15 August"


def test_a_film_over_several_years_puts_the_year_in_every_day() -> None:
    """ "Vitrac, Monday 15 August" and "Saturday 15 August" were different years of one film."""
    assert day_label("2016-08-15", "en", year=True) == "Monday 15 August 2016"
    assert home_name(["2016-08-15"], ["Vitrac"], "fr", year=True)[0] == (
        "Vitrac, lundi 15 août 2016"
    )
    assert outing_name(["2026-08-15"], [], "de", year=True)[0] == "Samstag, 15. August 2026"
