"""A walking or cycling trip gets a location card when its town changes, not only after 30 km."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from immich_memories.processing.assembly_config import AssemblyClip
from immich_memories.processing.title_divider_planner import TitleDividerPlanner

# Villages 12-18 km apart along a hiking route, far from a home at (0, 0).
VILLAGE_A = (50.90, 14.00, "Village A, Germany")
VILLAGE_B = (50.95, 14.20, "Village B, Germany")
VILLAGE_C = (51.02, 14.40, "Village C, Germany")
HOME = (48.00, 11.00, "Home Town, Germany")


def _clip(place: tuple[float, float, str], day: int) -> AssemblyClip:
    lat, lon, name = place
    return AssemblyClip(
        path=Path(f"{name}-{day}.mp4"),
        duration=5.0,
        date=f"2022-04-{day:02d}",
        latitude=lat,
        longitude=lon,
        location_name=name,
    )


def _planner(**settings) -> TitleDividerPlanner:
    generator = MagicMock()
    generator.generate_location_card_screen.side_effect = lambda name, **_: MagicMock(
        path=Path(f"/tmp/{name}.mp4")
    )
    title_settings = MagicMock()
    title_settings.month_divider_duration = 2.0
    title_settings.max_dividers = None
    title_settings.map_tiles = False
    title_settings.locale = "en"
    title_settings.home_lat, title_settings.home_lon = HOME[0], HOME[1]
    for key, value in settings.items():
        setattr(title_settings, key, value)
    return TitleDividerPlanner(generator, title_settings)


def _cards(result: list[AssemblyClip]) -> list[str]:
    return [clip.asset_id for clip in result if clip.is_title_screen]


def test_a_hike_from_village_to_village_gets_a_card_for_each_new_town():
    clips = [
        _clip(VILLAGE_A, 4),
        _clip(VILLAGE_A, 4),
        _clip(VILLAGE_B, 5),
        _clip(VILLAGE_B, 5),
        _clip(VILLAGE_C, 6),
    ]

    result = _planner().build_clips_with_location_dividers(clips, None)

    assert _cards(result) == ["location_Village B, Germany", "location_Village C, Germany"]
    assert result[2].is_title_screen


def test_a_day_that_passes_through_several_towns_gets_one_card():
    clips = [_clip(VILLAGE_A, 4), _clip(VILLAGE_B, 5), _clip(VILLAGE_C, 5), _clip(VILLAGE_B, 5)]

    result = _planner().build_clips_with_location_dividers(clips, None)

    assert _cards(result) == ["location_Village B, Germany"]


def test_a_town_is_not_carded_twice_in_a_row():
    clips = [_clip(VILLAGE_A, 4), _clip(VILLAGE_B, 5), _clip(VILLAGE_A, 5), _clip(VILLAGE_B, 6)]

    result = _planner().build_clips_with_location_dividers(clips, None)

    assert _cards(result) == ["location_Village B, Germany"]


def test_a_town_change_near_home_gets_no_card():
    near_home = (48.05, 11.05, "Next Door, Germany")
    clips = [_clip(VILLAGE_A, 4), _clip(near_home, 5), _clip(HOME, 6)]

    result = _planner().build_clips_with_location_dividers(clips, None)

    # The long hop back is the unchanged 30 km rule; the short one into home is no new town.
    assert _cards(result) == ["location_Next Door, Germany"]


def test_the_long_hop_rule_still_cards_a_new_city_on_the_same_day():
    barcelona = (41.39, 2.17, "Barcelona, Spain")
    paris = (48.86, 2.35, "Paris, France")
    clips = [_clip(VILLAGE_A, 4), _clip(VILLAGE_B, 4), _clip(barcelona, 4), _clip(paris, 4)]

    result = _planner(home_lat=None, home_lon=None).build_clips_with_location_dividers(clips, None)

    assert _cards(result) == [
        "location_Village B, Germany",
        "location_Barcelona, Spain",
        "location_Paris, France",
    ]
