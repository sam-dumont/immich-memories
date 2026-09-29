"""Map seconds past a regular card go on top of the film; they never eat content time.

Public city coordinates and invented place names only.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from immich_memories.processing.assembly_config import AssemblyClip, TitleScreenSettings
from immich_memories.processing.film_timeline import measure_film_timeline
from immich_memories.processing.timeline_budget import finalize_selected_timeline, plan_timeline
from immich_memories.processing.title_divider_planner import TitleDividerPlanner
from immich_memories.titles.generator import GeneratedScreen

_PLACES = [("Northtown", 48.86, 2.35), ("Midtown", 45.76, 4.84), ("Southtown", 43.30, 5.37)]
_PLACES.append(("Easttown", 43.70, 7.26))


class _MoveCards:
    def generate_location_card_screen(self, location_name, lat=None, lon=None):
        raise AssertionError("map tiles are on: every card is a move")

    def generate_location_move_screen(self, location_name, came_from, destination, seconds):
        return GeneratedScreen(Path(f"/{location_name}.mp4"), seconds, "location_card")


def _selected() -> list[AssemblyClip]:
    # 12 clips of 15 s, three per place: 180 s of pictures, three place changes.
    return [
        AssemblyClip(
            path=Path(f"/{name}{i}.mp4"),
            duration=15.0,
            asset_id=f"{name}{i}",
            date=str(date(2024, 7, 1 + index)),
            latitude=lat,
            longitude=lon,
            location_name=name,
        )
        for index, (name, lat, lon) in enumerate(_PLACES)
        for i in range(3)
    ]


def test_a_three_minute_trip_keeps_its_content_and_puts_the_map_extra_on_top() -> None:
    titles = TitleScreenSettings(
        memory_type="trip", map_tiles=True, title_duration=3.5, ending_duration=7.0
    )
    preliminary = plan_timeline([], titles, 180.0, "trip")
    plan = finalize_selected_timeline(
        preliminary, _selected(), selected_duration=180.0, title_settings=titles, memory_type="trip"
    )
    titles.max_dividers = plan.max_dividers
    titles.month_divider_duration = plan.divider_duration
    cards = TitleDividerPlanner(_MoveCards(), titles).build_clips_with_location_dividers(
        _selected(), None
    )
    intro = AssemblyClip(Path("/intro.mp4"), 7.2, asset_id="title_screen", is_title_screen=True)
    ending = AssemblyClip(Path("/end.mp4"), 7.0, asset_id="ending_screen", is_title_screen=True)

    timeline = measure_film_timeline([intro, *cards, ending], titles)

    assert plan.max_dividers == 3
    assert plan.content_budget == pytest.approx(180.0 - 3.5 - 7.0 - 3 * 2.0)
    assert timeline.title_seconds == pytest.approx(3.5 + 7.0 + 3 * 2.0)
    card_seconds = sum(c.duration for c in cards if c.is_title_screen)
    assert timeline.map_extra_seconds == pytest.approx((7.2 - 3.5) + card_seconds - 3 * 2.0)
    assert timeline.map_extra_seconds > 15.0


def test_a_render_longer_by_its_map_extra_is_on_budget(tmp_path) -> None:
    from immich_memories.config_loader import Config
    from immich_memories.generate import GenerationError, GenerationParams
    from immich_memories.generate_timeline import validate_final_duration

    params = GenerationParams(
        clips=[],
        output_path=tmp_path / "film.mp4",
        config=Config(),
        target_duration_seconds=180.0,
    )

    assert validate_final_duration(params, 200.0, map_extra_seconds=20.0) is None
    with pytest.raises(GenerationError, match="duration budget"):
        validate_final_duration(params, 200.0)


def test_the_run_record_and_its_report_carry_the_map_extra() -> None:
    from immich_memories.processing.film_timeline import FilmTimeline
    from immich_memories.tracking.models import RunMetadata
    from immich_memories.tracking.report import build_report
    from immich_memories.tracking.report_privacy import ReportPrivacy
    from immich_memories.tracking.run_database import RunDatabase
    from immich_memories.tracking.run_tracker import RunTracker
    from immich_memories.tracking.timing import Collector

    tracker = RunTracker("map-run", capture_system=False)
    tracker.start_run()
    tracker.record_film_timeline(FilmTimeline(163.5, 16.5, 21.04))

    run = RunDatabase().get_run("map-run")
    assert run is not None
    expected = {"content_seconds": 163.5, "title_seconds": 16.5, "map_extra_seconds": 21.0}
    assert run.film_timeline == expected
    assert RunMetadata.from_dict(run.to_dict()).film_timeline == expected
    report = build_report(run, Collector(), privacy=ReportPrivacy())
    assert report.data["run"]["timeline"] == expected
