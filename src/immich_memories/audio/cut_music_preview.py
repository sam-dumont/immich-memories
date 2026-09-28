"""Hear the music a cut would get before rendering it.

The track is generated the way the render generates one: a timeline from the cut's own clip
lengths and months, and the mood the cut's text reads as. `music preview` in the terminal and the
web client's preview both come here; the file it returns renders with `runs render --music`.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from immich_memories.audio.music_generator import generate_music_for_video
from immich_memories.audio.music_generator_client import MusicGenClientConfig
from immich_memories.audio.music_generator_models import VideoTimeline
from immich_memories.audio.text_mood import mood_for_cut
from immich_memories.processing.render_inputs import read_render_inputs

if TYPE_CHECKING:
    from collections.abc import Callable

    from immich_memories.config_loader import Config


class PreviewUnavailable(RuntimeError):
    """No track could be made for this cut; the message says why."""


def _timeline(config: Config, attempt_dir: Path) -> VideoTimeline:
    inputs = read_render_inputs(attempt_dir)
    if inputs is None:
        raise PreviewUnavailable("This cut kept no render inputs. Cut again to preview its music.")
    rows = []
    for clip in inputs.clips:
        start, end = inputs.segments.get(clip.asset.id, (0.0, clip.duration_seconds or 5.0))
        created = clip.asset.file_created_at
        rows.append((end - start, "calm", created.month if created else None))
    titles = config.title_screens
    return VideoTimeline.from_clips(
        clips=rows,
        title_duration=titles.title_duration if titles.enabled else 0,
        ending_duration=titles.ending_duration if titles.enabled else 0,
    )


async def preview_music_for_cut(
    config: Config,
    attempt_dir: Path,
    output_dir: Path,
    progress: Callable[[int, str, float, str], None] | None = None,
) -> Path:
    """Generate one version of this cut's music into `output_dir` and return the mix."""
    if not (config.musicgen.enabled or config.ace_step.enabled):
        raise PreviewUnavailable(
            "No music generator is configured: set advanced.musicgen.enabled or "
            "advanced.ace_step.enabled to preview a track."
        )
    timeline = _timeline(config, attempt_dir)
    inputs = read_render_inputs(attempt_dir)
    ids = tuple(clip.asset.id for clip in inputs.clips) if inputs else ()
    choice = await mood_for_cut(config, attempt_dir, ids)
    for clip in timeline.clips:
        clip.mood = choice.mood.primary_mood
    service = MusicGenClientConfig.from_app_config(config.musicgen)
    service.num_versions = 1
    output_dir.mkdir(parents=True, exist_ok=True)
    result = await generate_music_for_video(
        timeline=timeline,
        output_dir=output_dir,
        config=service,
        progress_callback=progress,
        app_config=config,
        mood_detail=choice.mood,
    )
    if not result or not result.versions:
        raise PreviewUnavailable("No music service produced a track for this cut.")
    return Path(result.versions[0].full_mix)
