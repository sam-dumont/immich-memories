"""The trip intro names every stop, and names a cluster of close ones once.

Every place name here is invented and every coordinate is a round public one.
"""

from __future__ import annotations

from immich_memories.titles.trip_stops import group_trip_stops

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


def test_a_cluster_with_no_shared_level_is_named_first_to_last() -> None:
    def no_common_level(lat: float, lon: float) -> dict[str, str]:
        return {"village": "x", "county": f"County {lat:.2f}"}

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
