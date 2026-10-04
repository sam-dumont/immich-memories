"""The plan names where the film lands, not a path it never gets."""

from __future__ import annotations

from pathlib import Path

from immich_memories.cli._generation_preview import GenerationPreview, print_generation_preview
from immich_memories.processing.output_canvas import OutputCanvas
from immich_memories.processing.timeline_budget import TimelinePlan


def test_the_planned_output_shows_the_folder_and_name_the_film_lands_at(capsys) -> None:
    print_generation_preview(
        GenerationPreview(
            memory_type="album",
            date_range="Jun 2021",
            video_candidates=1,
            live_photo_candidates=0,
            photo_candidates=9,
            selected_videos=1,
            selected_photos=9,
            selected_duration=40.0,
            timeline=TimelinePlan(
                target_duration=60.0,
                content_budget=50.0,
                title_budget=9.5,
                title_duration=3.5,
                ending_duration=4.0,
                divider_duration=2.0,
                max_dividers=1,
                transition_budget=4.0,
            ),
            canvas=OutputCanvas(width=1280, height=720, orientation="landscape"),
            output_path=Path("/films/album_first_film.mp4"),
            upload_intent=False,
            music_policy="disabled",
        )
    )

    line = next(
        line for line in capsys.readouterr().out.splitlines() if line.startswith("Output (planned)")
    )
    assert line == (
        "Output (planned): /films/album_first_film_<recipe>_<run id>/album_first_film_<recipe>.mp4"
    )
