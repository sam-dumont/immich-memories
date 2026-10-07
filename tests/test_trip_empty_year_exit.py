"""A trip request for a year with no trips fails like every other unsatisfiable request (#2089)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from tests.test_trip_photo_gps import _trip_config


def _generate_trips_for_a_year_with_none():
    from immich_memories.cli._trip_generation import handle_trip_generation

    with (
        # WHY: trip detection reads the whole library from Immich; an empty answer is the case.
        patch("immich_memories.cli._trip_display.run_trip_detection", return_value=[]),
        patch("immich_memories.cli._trip_display.format_trips_table", return_value=""),
    ):
        handle_trip_generation(
            client=MagicMock(),
            config=_trip_config(),
            progress=MagicMock(),
            year=1999,
            month=None,
            trip_index=None,
            all_trips=False,
            near_date=None,
            person_names=[],
            output_path=MagicMock(),
            use_live_photos=False,
            use_photos=True,
            transition="smart",
            music=None,
            music_volume=0.5,
            no_music=True,
            resolution="auto",
            scale_mode=None,
            output_format=None,
            add_date=False,
            add_place=False,
            keep_intermediates=False,
            privacy_mode=False,
            title_override=None,
            subtitle_override=None,
            upload_to_immich=False,
            album=None,
            source="auto",
            memory_key="trip:key",
            memory_category="trip",
            automation_attempt_id="attempt-trip-1",
            dry_run=True,
        )


def test_a_year_with_no_trips_exits_one():
    with pytest.raises(SystemExit) as exited:
        _generate_trips_for_a_year_with_none()

    assert exited.value.code == 1
