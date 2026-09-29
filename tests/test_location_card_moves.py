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
