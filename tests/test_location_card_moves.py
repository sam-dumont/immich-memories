"""Every location card flies from the place before it and lasts as long as the flight.

Public city coordinates and invented place names only.
"""

from __future__ import annotations

from pathlib import Path

from immich_memories.processing.assembly_config import AssemblyClip, TitleScreenSettings
from immich_memories.processing.title_divider_planner import TitleDividerPlanner
from immich_memories.titles.generator import GeneratedScreen

_NORTH, _MIDDLE, _SOUTH = (48.86, 2.35), (45.76, 4.84), (43.30, 5.37)


class _Cards:
    """Records what each card was asked to show; renders nothing."""

    def __init__(self) -> None:
        self.moves: list[tuple[str, tuple[float, float], tuple[float, float], float]] = []
        self.stills: list[str] = []

    def generate_month_divider(self, month, year=None, is_birthday_month=False):
        raise AssertionError("a trip gets no month dividers")

    def generate_year_divider(self, year):
        raise AssertionError("a trip gets no year dividers")

    def generate_location_card_screen(self, location_name, lat=None, lon=None):
        self.stills.append(location_name)
        return GeneratedScreen(Path(f"/still/{location_name}.mp4"), 2.0, "location_card")

    def generate_location_move_screen(self, location_name, came_from, destination, seconds):
        self.moves.append((location_name, came_from, destination, seconds))
        return GeneratedScreen(Path(f"/move/{location_name}.mp4"), seconds, "location_card")


def _clip(name: str, point: tuple[float, float]) -> AssemblyClip:
    return AssemblyClip(
        path=Path(f"/{name}.mp4"),
        duration=4.0,
        asset_id=name,
        latitude=point[0],
        longitude=point[1],
        location_name=name,
    )


def _trip() -> list[AssemblyClip]:
    return [_clip("Northtown", _NORTH), _clip("Midtown", _MIDDLE), _clip("Southtown", _SOUTH)]


def test_each_card_flies_from_the_last_place_and_runs_its_flight_length() -> None:
    cards = _Cards()
    planner = TitleDividerPlanner(cards, TitleScreenSettings(map_tiles=True))

    timeline = planner.build_clips_with_location_dividers(_trip(), None)

    assert [move[:3] for move in cards.moves] == [
        ("Midtown", _NORTH, _MIDDLE),
        ("Southtown", _MIDDLE, _SOUTH),
    ]
    card_lengths = [clip.duration for clip in timeline if clip.is_title_screen]
    assert card_lengths == [move[3] for move in cards.moves]
    assert all(6.0 <= seconds <= 8.0 for seconds in card_lengths)
    assert card_lengths[0] > card_lengths[1]  # 390 km flies longer than 270 km


def test_without_map_tiles_a_card_stays_the_regular_still() -> None:
    cards = _Cards()
    planner = TitleDividerPlanner(
        cards, TitleScreenSettings(map_tiles=False, month_divider_duration=2.0)
    )

    timeline = planner.build_clips_with_location_dividers(_trip(), None)

    assert cards.moves == []
    assert [clip.duration for clip in timeline if clip.is_title_screen] == [2.0, 2.0]


# Invented villages 12-18 km apart on a walking route, far from home.
_VILLAGE_A, _VILLAGE_B, _VILLAGE_C = (50.90, 14.00), (50.95, 14.20), (51.02, 14.40)


def _walk() -> list[AssemblyClip]:
    route = [
        ("Village A", _VILLAGE_A, 4),
        ("Village A", _VILLAGE_A, 4),
        ("Village B", _VILLAGE_B, 5),
        ("Village C", _VILLAGE_C, 6),
    ]
    return [
        AssemblyClip(
            path=Path(f"/{name}{day}.mp4"),
            duration=15.0,
            asset_id=f"{name}{day}{i}",
            date=f"2024-07-{day:02d}",
            latitude=point[0],
            longitude=point[1],
            location_name=name,
        )
        for i, (name, point, day) in enumerate(route)
    ]


def test_a_walk_flies_each_new_town_from_the_last_named_one_and_the_budget_counts_them() -> None:
    from immich_memories.processing.film_timeline import measure_film_timeline
    from immich_memories.processing.map_move_timing import MapMoveTiming
    from immich_memories.processing.timeline_budget import (
        finalize_selected_timeline,
        plan_timeline,
    )

    titles = TitleScreenSettings(memory_type="trip", map_tiles=True, home_lat=48.0, home_lon=11.0)
    plan = finalize_selected_timeline(
        plan_timeline([], titles, 120.0, "trip"),
        _walk(),
        selected_duration=60.0,
        title_settings=titles,
        memory_type="trip",
    )
    titles.max_dividers = plan.max_dividers
    cards = _Cards()

    timeline = TitleDividerPlanner(cards, titles).build_clips_with_location_dividers(_walk(), None)

    assert [move[:3] for move in cards.moves] == [
        ("Village B", _VILLAGE_A, _VILLAGE_B),
        ("Village C", _VILLAGE_B, _VILLAGE_C),
    ]
    assert plan.max_dividers == 2
    assert plan.title_budget == titles.title_duration + titles.ending_duration + 2 * 2.0
    frames = MapMoveTiming().schedule(cards.moves[0][3], fps=30.0)
    assert frames[-60:] == [1.0] * 60
    assert measure_film_timeline(timeline, titles).map_extra_seconds == sum(
        seconds - 2.0 for *_, seconds in cards.moves
    )
