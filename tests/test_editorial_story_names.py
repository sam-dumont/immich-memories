"""A story is called by the one thing it is, from its facts (#2486)."""

from __future__ import annotations

from immich_memories.analysis.editorial_story_names import (
    day_label,
    home_name,
    leg_name,
    span_label,
    trip_name,
    trip_purpose,
)


def test_a_day_reads_as_a_person_writes_it() -> None:
    assert day_label("2025-07-06") == "Sunday 6 July"


def test_a_span_of_days_reads_as_a_person_writes_it() -> None:
    assert span_label("2025-07-01", "2025-07-04") == "1–4 July"
    assert span_label("2025-06-30", "2025-07-02") == "30 June – 2 July"
    assert span_label("2025-07-05", "2025-07-05") == "5 July"


def test_days_at_home_are_their_span_never_a_list_of_activities() -> None:
    name, purpose = home_name(
        ["2025-07-01", "2025-07-02", "2025-07-04"], ["Ganshoren", "Schaerbeek", "Jette", "Forest"]
    )
    assert name == "Days at home, 1–4 July"
    assert purpose == "Ordinary days at home: Ganshoren, Schaerbeek, Jette and 1 more places"
    assert " / " not in name


def test_one_day_at_one_place_names_the_place() -> None:
    assert home_name(["2025-07-06"], ["Tervuren", "Tervuren"])[0] == "Tervuren, Sunday 6 July"
    assert home_name(["2025-07-06"], ["Tervuren", "Vossem"])[0] == "Sunday 6 July"


def test_a_trip_is_its_album_else_where_it_reached() -> None:
    assert trip_name(album="The road north", farthest="Nordkapp") == "The road north"
    assert trip_name(album=None, farthest="Nordkapp") == "Trip to Nordkapp"


def test_a_leg_runs_from_its_first_place_to_its_last() -> None:
    places = ["Copenhagen", "Gränna", "Nordkapp"]
    assert leg_name(places, trip="The road north", legs=3) == "Copenhagen to Nordkapp"
    assert leg_name(places, trip="The road north", legs=1) == "The road north"


def test_a_trips_purpose_states_its_days_and_ends() -> None:
    days = ["2025-07-12", "2025-07-20", "2025-07-30"]
    assert trip_purpose(days, ["Copenhagen", "Nordkapp", "Kristiansand"]) == (
        "19 days away, Copenhagen to Kristiansand"
    )
