"""A trip that changes where it stays splits into legs; one that keeps moving or stays put does not."""

from __future__ import annotations

import pytest

from immich_memories.analysis.trip_legs import legs_of_days

KM = 1 / 111.0  # degrees of latitude per kilometre


def _day(n: int) -> str:
    return f"2022-04-{n:02d}"


def _at(north_km: float, east_km: float = 0.0, *, pictures: int = 5):
    lat, lon = 50.0 + north_km * KM, 14.0 + east_km * KM * 1.55
    return [(lat, lon)] * pictures


def test_a_hike_then_a_city_stay_is_two_legs():
    # Six days walking 6-9 km a day, a transfer of about 185 km, three days in one city.
    hike = {_day(4 + i): _at(i * 7.0) for i in range(6)}
    city = {_day(10 + i): _at(185.0, 5.0 + i) for i in range(3)}

    legs = legs_of_days({**hike, **city})

    assert {legs[d] for d in hike} == {0}
    assert {legs[d] for d in city} == {1}


def test_a_road_trip_that_moves_every_day_is_one_leg():
    road = {_day(1 + i): _at(i * 60.0) for i in range(10)}

    assert set(legs_of_days(road).values()) == {0}


def test_one_stay_with_day_trips_is_one_leg():
    stay = {_day(1 + i): _at(0.0) for i in range(8)}
    stay[_day(3)] = _at(12.0)
    stay[_day(6)] = _at(0.0, 14.0)

    assert set(legs_of_days(stay).values()) == {0}


def test_two_stays_closer_than_the_transfer_are_one_leg():
    first = {_day(1 + i): _at(0.0) for i in range(4)}
    second = {_day(5 + i): _at(40.0) for i in range(4)}

    assert set(legs_of_days({**first, **second}).values()) == {0}


def test_a_travel_day_and_a_day_without_positions_join_a_leg():
    hike = {_day(4 + i): _at(i * 7.0) for i in range(5)}
    travel = {_day(9): _at(90.0)}
    city = {_day(10 + i): _at(185.0) for i in range(3)}
    unplaced = {_day(13): []}

    legs = legs_of_days({**hike, **travel, **city, **unplaced})

    assert legs[_day(9)] in (0, 1)
    assert legs[_day(13)] == 1
    assert sorted(set(legs.values())) == [0, 1]


@pytest.mark.parametrize("area_km", [15.0, 25.0, 40.0])
def test_the_split_does_not_hang_on_the_area_radius(area_km):
    hike = {_day(4 + i): _at(i * 3.0) for i in range(6)}
    city = {_day(10 + i): _at(185.0) for i in range(3)}
    road = {_day(1 + i): _at(i * 60.0) for i in range(10)}

    assert set(legs_of_days({**hike, **city}, area_km=area_km).values()) == {0, 1}
    assert set(legs_of_days(road, area_km=area_km).values()) == {0}
