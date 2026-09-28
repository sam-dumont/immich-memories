"""Saved and live previews place the same cards as assembly."""

from pathlib import Path

from immich_memories.processing.assembly_config import AssemblyClip, TitleScreenSettings
from immich_memories.processing.timeline_budget import TimelinePlan
from immich_memories.processing.timeline_preview import preview_timeline


def test_the_title_and_ending_hold_less_of_the_clips_they_play():
    """The film the preview promises is the one assembly renders.

    A content-backed title plays its first clip's opening half-second in slow
    motion, and the ending the last clip's closing one, so those clips hold
    half a second less on screen.
    """
    clips = [
        AssemblyClip(Path(), 4, date=f"{year}-01-01", asset_id=str(year)) for year in (2023, 2024)
    ]
    plan = TimelinePlan(30, 20, 10, 3, 5, 2, 1)
    starts, seconds = preview_timeline(
        clips, plan, TitleScreenSettings(divider_mode="year"), "cut", 0.5
    )
    assert starts == {"2023": (3, 3.5), "2024": (8.5, 3.5)}
    assert seconds == 17


def test_trip_map_and_location_card_use_real_source_places():
    clips = [
        AssemblyClip(Path(), 4, asset_id="a", latitude=0, longitude=0, location_name="A"),
        AssemblyClip(Path(), 4, asset_id="b", latitude=1, longitude=0, location_name="B"),
    ]
    plan = TimelinePlan(30, 20, 10, 3, 5, 2, 1)
    starts, seconds = preview_timeline(
        clips, plan, TitleScreenSettings(memory_type="trip"), "crossfade", 0.5
    )
    # A map intro shows no clip, so only the ending borrows.
    assert starts == {"a": (2.5, 4), "b": (7.5, 3.5)}
    assert seconds == 16
