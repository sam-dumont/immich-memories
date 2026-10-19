"""Title and divider rendering keeps reporting progress, card by card and frame by frame.

A render worker's stall guard reads a phase, fraction and message that stop changing as a
dead worker (#2694). A trip with many stops spent more than 20 minutes rendering its
location cards behind one "Generating location cards..." line, so the film was thrown away.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from immich_memories.processing.assembly_config import (
    AssemblyClip,
    AssemblySettings,
    TitleScreenSettings,
    standalone_assembly_encoding_plan,
)
from immich_memories.processing.title_divider_planner import TitleDividerPlanner
from immich_memories.processing.title_inserter import TitleInserter

# Made-up stops, far enough apart that each one gets its own card.
NORTHTOWN = (10.0, 20.0, "Northtown")
EASTBAY = (10.0, 21.0, "Eastbay")
SOUTHFORD = (9.0, 21.0, "Southford")
WESTMOOR = (9.0, 20.0, "Westmoor")


def _clip(place: tuple[float, float, str], date: str, name: str | None = None) -> AssemblyClip:
    lat, lon, town = place
    return AssemblyClip(
        path=Path(f"/{name or town}-{date}.mp4"),
        asset_id=name or f"{town}-{date}",
        duration=4.0,
        date=date,
        latitude=lat,
        longitude=lon,
        location_name=town,
    )


def _trip() -> list[AssemblyClip]:
    return [
        _clip(NORTHTOWN, "2022-04-01"),
        _clip(EASTBAY, "2022-04-02"),
        _clip(SOUTHFORD, "2022-04-03"),
        _clip(WESTMOOR, "2022-04-04"),
    ]


def _screen(name: str, seconds: float = 2.0) -> SimpleNamespace:
    return SimpleNamespace(path=Path(f"/cards/{name}.mp4"), duration=seconds)


def _rendering_generator() -> MagicMock:
    """A card generator that reports its frames the way the real map renderer does."""

    def map_move(name, came_from, destination, seconds, frame_progress=None):
        for frame in (0, 10, 20):
            if frame_progress is not None:
                frame_progress(frame, 20)
        return _screen(name, seconds)

    generator = MagicMock()
    generator.generate_location_move_screen.side_effect = map_move
    generator.generate_location_card_screen.side_effect = lambda name, **_: _screen(name)
    generator.generate_month_divider.side_effect = lambda month, year, **_: _screen(
        f"{year}-{month}"
    )
    generator.generate_year_divider.side_effect = lambda year: _screen(str(year))
    return generator


def _assert_moves_forward(calls: list[tuple[float, str]]) -> None:
    fractions = [fraction for fraction, _ in calls]
    assert fractions == sorted(fractions), calls
    assert all(0.0 <= fraction <= 1.0 for fraction in fractions), calls


@pytest.mark.parametrize("map_tiles", [False, True])
def test_each_location_card_reports_its_own_step(map_tiles: bool) -> None:
    calls: list[tuple[float, str]] = []
    settings = TitleScreenSettings(memory_type="trip", map_tiles=map_tiles, max_dividers=None)
    planner = TitleDividerPlanner(_rendering_generator(), settings)

    planner.build_clips_with_location_dividers(_trip(), lambda f, m: calls.append((f, m)))

    messages = [message for _, message in calls]
    for card in (1, 2, 3):
        assert any(message.startswith(f"Location card {card} of 3") for message in messages)
    _assert_moves_forward(calls)


def test_a_map_card_reports_while_its_frames_render() -> None:
    calls: list[tuple[float, str]] = []
    settings = TitleScreenSettings(memory_type="trip", map_tiles=True, max_dividers=None)
    planner = TitleDividerPlanner(_rendering_generator(), settings)

    planner.build_clips_with_location_dividers(_trip(), lambda f, m: calls.append((f, m)))

    first_card = [(f, m) for f, m in calls if m.startswith("Location card 1 of 3")]
    # Three frame reports after the card's own step: each one is new to a stall guard.
    assert len(set(first_card)) >= 4, first_card


def test_each_month_divider_reports_its_own_step() -> None:
    calls: list[tuple[float, str]] = []
    clips = [
        _clip(NORTHTOWN, "2022-01-05"),
        _clip(NORTHTOWN, "2022-02-05"),
        _clip(NORTHTOWN, "2022-03-05"),
        _clip(NORTHTOWN, "2022-04-05"),
    ]
    settings = TitleScreenSettings(divider_mode="month", max_dividers=None)
    planner = TitleDividerPlanner(_rendering_generator(), settings)

    planner.generate_month_dividers(clips, lambda f, m: calls.append((f, m)))

    messages = [message for _, message in calls]
    for card in (1, 2, 3, 4):
        assert f"Month divider {card} of 4" in messages
    _assert_moves_forward(calls)


def test_each_year_divider_reports_its_own_step() -> None:
    calls: list[tuple[float, str]] = []
    clips = [
        _clip(NORTHTOWN, "2019-06-01"),
        _clip(NORTHTOWN, "2020-06-01"),
        _clip(NORTHTOWN, "2021-06-01"),
        _clip(NORTHTOWN, "2022-06-01"),
    ]
    settings = TitleScreenSettings(divider_mode="year", max_dividers=None)
    planner = TitleDividerPlanner(_rendering_generator(), settings)

    planner.generate_year_dividers(clips, lambda f, m: calls.append((f, m)))

    messages = [message for _, message in calls]
    for card in (1, 2, 3, 4):
        assert f"Year divider {card} of 4" in messages
    _assert_moves_forward(calls)


@pytest.fixture
def no_external_work(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("progress tests must not run media tools or services")

    monkeypatch.setattr("socket.socket.connect", forbidden)
    monkeypatch.setattr("subprocess.run", forbidden)
    monkeypatch.setattr("subprocess.Popen", forbidden)


def test_a_trip_film_titles_its_stages_in_order_and_never_goes_back(
    tmp_path, monkeypatch, no_external_work
) -> None:
    """Opening map, location cards, ending, encode: one fraction that only moves forward."""
    generator = _rendering_generator()

    def frames(screen):
        def render(*_args, frame_progress=None, **_kwargs):
            for frame in (0, 10, 20):
                if frame_progress is not None:
                    frame_progress(frame, 20)
            return screen

        return render

    generator.generate_trip_map_screen.side_effect = frames(_screen("intro", 7.0))
    generator.generate_ending_screen.side_effect = frames(_screen("ending", 4.0))
    # WHY: the title generator renders video through FFmpeg and the GPU; the planner and
    # inserter around it are what this test runs.
    monkeypatch.setattr("immich_memories.titles.TitleScreenGenerator", lambda **_kw: generator)
    settings = AssemblySettings(
        encoding_plan=standalone_assembly_encoding_plan(),
        title_screens=TitleScreenSettings(
            memory_type="trip",
            map_tiles=True,
            max_dividers=None,
            trip_locations=[(10.0, 20.0)],
            trip_title_text="FOUR DAYS AWAY",
            home_lat=12.0,
            home_lon=22.0,
        ),
    )
    inserter = TitleInserter(settings, MagicMock())
    monkeypatch.setattr(inserter, "_resolve_assembly_params", lambda _clips: (320, 180, 30, "sdr"))
    monkeypatch.setattr(
        inserter.background_renderer, "render_last_clip", lambda *_a, **_kw: tmp_path / "tail.mp4"
    )
    calls: list[tuple[float, str]] = []

    def assemble(final, output_path, progress):
        progress(0.5, "Encoding")
        return output_path

    inserter.assemble_with_titles(
        _trip(), tmp_path / "out.mp4", assemble, lambda f, m: calls.append((f, m))
    )

    _assert_moves_forward(calls)
    messages = [message for _, message in calls]
    stages = ["Generating trip map", "Location card", "Generating ending screen", "Encoding"]
    firsts = [next(i for i, m in enumerate(messages) if m.startswith(s)) for s in stages]
    assert firsts == sorted(firsts), messages
    # The intro and the ending each report while their frames render.
    for stage in ("Generating trip map", "Generating ending screen"):
        assert len({c for c in calls if c[1].startswith(stage)}) >= 3, calls
