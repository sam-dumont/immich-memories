"""The trip intro names every stop, and names a cluster of close ones once.

Public cities and invented villages, with round public coordinates.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from immich_memories.i18n import SUPPORTED_LOCALES
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


# Real Nominatim answers for two Greek points, captured per locale (and the product's
# own accept-language chain, never "en") in tests/fixtures/places/greece_platanias_
# <locale>.json and greece_chania_<locale>.json (#1954, #1947). French first, then
# every supported locale.
_PLATANIAS_LOCALES = ["fr", *[loc for loc in SUPPORTED_LOCALES if loc != "fr"]]


def _fixture_address(name: str, locale: str) -> dict[str, str]:
    path = Path(__file__).parent / "fixtures" / "places" / f"{name}_{locale}.json"
    return json.loads(path.read_text())["address"]


@pytest.mark.parametrize("locale", _PLATANIAS_LOCALES)
def test_two_villages_in_one_municipality_share_the_municipalitys_name(locale) -> None:
    """Two villages merged into one municipality, as #1954's case actually looked.

    English and German's own municipality translations are nominative and strip
    cleanly to "Platanias". Every other locale's real answer is Greek's genitive
    "Δήμος Πλατανιά" ("of Platanias"); dropping "Δήμος" would leave the declined
    fragment "Πλατανιά", so it must name nothing at this scale and fall back to the
    villages' own (nominative) names instead.
    """
    municipality = _fixture_address("greece_platanias", locale)["municipality"]

    def address(_lat, _lon):
        return {"municipality": municipality, "country": "Greece"}

    stops = group_trip_stops(_VALLEY[:3], _VILLAGES[:3], address)

    expected = "Platanias" if locale in ("en", "de") else "Village A → Village C"
    assert [stop.name for stop in stops] == [expected]


@pytest.mark.parametrize("locale", _PLATANIAS_LOCALES)
def test_a_municipality_cluster_with_no_member_names_shows_the_degraded_name(locale) -> None:
    """Owner's ruling: when nothing nominative names a pin at all -- no shared

    city/town/village, and the cluster's own members have no name either -- the admin
    word is dropped from the inflected municipality anyway ("Δήμος Πλατανιά" ->
    "Πλατανιά"), declined grammar and all, rather than dropping the stop.
    """
    municipality = _fixture_address("greece_platanias", locale)["municipality"]

    def address(_lat, _lon):
        return {"municipality": municipality, "country": "Greece"}

    stops = group_trip_stops(_VALLEY[:3], ["", "", ""], address)

    expected = "Platanias" if locale in ("en", "de") else "Πλατανιά"
    assert [stop.name for stop in stops] == [expected]


@pytest.mark.parametrize("locale", _PLATANIAS_LOCALES)
def test_two_municipalities_fall_back_to_their_own_members(locale) -> None:
    """A trip leg from Platanias to Chania (~13 km, one map stop): the two real

    municipalities ("Δήμος Πλατανιά", "Δήμος Χανίων") never agree, so the shared
    name comes from their (also real) shared county next. English and German's
    county translations are nominative ("Chania Regional Unit", "Regionalbezirk
    Chania") and strip to "Chania". Every other locale's real county is Greek's
    genitive "Περιφερειακή Ενότητα Χανίων" ("of Chania"): not a name to decline,
    so the pin falls back to the villages themselves, first stop to last.
    """
    platanias = _fixture_address("greece_platanias", locale)
    chania = _fixture_address("greece_chania", locale)
    platanias_name = platanias["village"]
    chania_name = chania["city"]
    points = [(35.512, 23.879), (35.512, 23.879), (35.5138, 24.0180)]

    def address(lat: float, _lon: float) -> dict[str, str]:
        return platanias if lat < 35.513 else chania

    stops = group_trip_stops(points, [platanias_name, platanias_name, chania_name], address)

    expected = "Chania" if locale in ("en", "de") else f"{platanias_name} → {chania_name}"
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
