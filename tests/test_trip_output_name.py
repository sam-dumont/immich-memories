"""Where a trip's film is written: the path asked for, or one per trip beside it."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from immich_memories.analysis.trip_detection import DetectedTrip
from immich_memories.cli._trip_generation import trip_output_path

LAKE = DetectedTrip(
    start_date=date(2024, 6, 21),
    end_date=date(2024, 6, 27),
    location_name="Lake Annecy",
    asset_count=44,
    centroid_lat=45.9,
    centroid_lon=6.1,
)


def test_one_trip_with_an_explicit_output_is_written_there():
    asked = Path("/films/summer.mp4")

    assert trip_output_path(asked, LAKE, "mp4", explicit=True, several=False) == asked


def test_several_trips_with_an_explicit_output_keep_its_name_as_a_prefix():
    named = trip_output_path(Path("/films/summer.mp4"), LAKE, "mp4", explicit=True, several=True)

    assert named == Path("/films/summer-lake_annecy_2024-06-21.mp4")


def test_without_an_explicit_output_a_trip_is_named_after_itself():
    named = trip_output_path(Path("/films/default.mp4"), LAKE, "mov", explicit=False, several=False)

    assert named == Path("/films/trip_lake_annecy_2024-06-21.mov")
