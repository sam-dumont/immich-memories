"""The trip intro names every stop, and names a cluster of close ones once.

Public cities and invented villages, with round public coordinates.
"""

from __future__ import annotations

import pytest

from immich_memories.titles.trip_stops import group_trip_stops


def test_a_map_stop_in_one_city_does_not_zoom_out_to_its_region():
    points = [(48.85, 2.35), (48.86, 2.34), (48.87, 2.36)]

    def address(_lat, _lon):
        return {"city": "Paris", "state": "Île-de-France", "country": "France"}

    stops = group_trip_stops(points, ["Paris"] * 3, address)

    assert [stop.name for stop in stops] == ["Paris"]


# Seven invented villages strung along a valley, all within a few kilometres.
_VALLEY = [(46.00 + i * 0.01, 7.00 + i * 0.01) for i in range(7)]
_VILLAGES = [f"Village {letter}" for letter in "ABCDEFG"]


def _valley_address(lat: float, lon: float) -> dict[str, str]:
    index = round((lat - 46.00) / 0.01)
    return {"village": _VILLAGES[index], "county": "Invented Valley", "country": "Nowhere"}


def test_seven_close_villages_become_one_stop_with_the_name_they_share() -> None:
    stops = group_trip_stops(_VALLEY, _VILLAGES, _valley_address)

    assert len(stops) == 1
    assert stops[0].name == "Invented Valley"
    assert 46.00 < stops[0].lat < 46.06


def test_far_apart_towns_each_keep_their_own_name() -> None:
    towns = [(45.0, 5.0), (46.0, 6.0), (47.0, 7.0)]

    stops = group_trip_stops(towns, ["Northtown", "Midtown", "Southtown"], _valley_address)

    assert [stop.name for stop in stops] == ["Northtown", "Midtown", "Southtown"]


def test_a_shared_municipality_pin_drops_its_administrative_wording() -> None:
    # Greek OSM boundaries answer in English when the film's language has no
    # translation (#1954): the pin must still read the town, not the boilerplate.
    def address(_lat, _lon):
        return {"municipality": "Municipality of Platanias", "country": "Greece"}

    stops = group_trip_stops(_VALLEY[:3], _VILLAGES[:3], address)

    assert [stop.name for stop in stops] == ["Platanias"]


# Real municipality answers for the same Greek point (35.512, 23.879), captured per
# locale in tests/fixtures/places/greece_platanias_<locale>.json: no accept-language
# override past the film's own, so most locales get the native Greek name (#1954).
_PLATANIAS_PIN_BY_LOCALE = {
    "en": ("Municipality of Platanias", "Platanias"),
    "fr": ("Δήμος Πλατανιά", "Πλατανιά"),
    "nl": ("Δήμος Πλατανιά", "Πλατανιά"),
    "de": ("Provinz Platanias", "Platanias"),
    "es": ("Δήμος Πλατανιά", "Πλατανιά"),
    "it": ("Δήμος Πλατανιά", "Πλατανιά"),
    "pt-BR": ("Δήμος Πλατανιά", "Πλατανιά"),
    "pt-PT": ("Δήμος Πλατανιά", "Πλατανιά"),
    "pl": ("Δήμος Πλατανιά", "Πλατανιά"),
    "sv": ("Δήμος Πλατανιά", "Πλατανιά"),
    "ru": ("Δήμος Πλατανιά", "Πλατανιά"),
    "ja": ("Δήμος Πλατανιά", "Πλατανιά"),
    "zh-Hans": ("Δήμος Πλατανιά", "Πλατανιά"),
    "ko": ("Δήμος Πλατανιά", "Πλατανιά"),
}


@pytest.mark.parametrize("locale", sorted(_PLATANIAS_PIN_BY_LOCALE))
def test_a_shared_municipality_pin_keeps_its_native_name_in_every_locale(locale) -> None:
    raw_municipality, expected = _PLATANIAS_PIN_BY_LOCALE[locale]

    def address(_lat, _lon):
        return {"municipality": raw_municipality, "country": "Greece"}

    stops = group_trip_stops(_VALLEY[:3], _VILLAGES[:3], address)

    assert [stop.name for stop in stops] == [expected]


def test_a_cluster_with_no_shared_level_is_named_first_to_last() -> None:
    def no_common_level(lat: float, lon: float) -> dict[str, str]:
        return {"village": f"Village {lat:.2f}", "county": f"County {lat:.2f}"}

    stops = group_trip_stops(_VALLEY, _VILLAGES, no_common_level)

    assert [stop.name for stop in stops] == ["Village A → Village G"]


def test_without_a_geocoder_a_cluster_still_gets_a_name() -> None:
    stops = group_trip_stops(_VALLEY, _VILLAGES)

    assert [stop.name for stop in stops] == ["Village A → Village G"]


def test_two_close_towns_keep_their_names_and_an_unnamed_point_is_no_dot() -> None:
    points = [(46.0, 7.0), (46.01, 7.01), (48.0, 2.0)]

    stops = group_trip_stops(points, ["Upper Ford", "Lower Ford", ""])

    assert [stop.name for stop in stops] == ["Upper Ford", "Lower Ford"]


def test_a_trip_film_opens_on_the_grouped_stops(tmp_path) -> None:
    from datetime import date
    from pathlib import Path

    from immich_memories.config_loader import Config
    from immich_memories.generate import GenerationParams
    from immich_memories.generate_settings import build_title_settings
    from immich_memories.processing.assembly_config import AssemblyClip

    config = Config()
    config.network.map_tiles = True
    clips = [
        AssemblyClip(
            path=Path(f"/clip{i}.mp4"),
            duration=4.0,
            asset_id=f"clip{i}",
            latitude=lat,
            longitude=lon,
            location_name=name,
        )
        for i, ((lat, lon), name) in enumerate(zip(_VALLEY, _VILLAGES, strict=True))
    ]
    params = GenerationParams(
        clips=[],
        output_path=tmp_path / "film.mp4",
        config=config,
        memory_type="trip",
        date_start=date(2024, 7, 1),
        date_end=date(2024, 7, 8),
        memory_preset_params={
            "location_name": "Nowhere",
            "trip_start": date(2024, 7, 1),
            "trip_end": date(2024, 7, 8),
        },
    )

    settings = build_title_settings(params, config, clips)

    assert settings is not None
    assert settings.trip_location_names == ["Village A → Village G"]
    assert settings.trip_locations is not None and len(settings.trip_locations) == 1
