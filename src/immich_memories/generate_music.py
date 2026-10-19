"""Music generation and mixing helpers for video generation.

Extracted from generate.py — handles AI music generation (MusicGen/ACE-Step),
music resolution, and audio mixing into assembled videos.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from immich_memories.delivery_timestamp import CARRY_CONTAINER_METADATA
from immich_memories.processing.assembly_config import AssemblyClip
from immich_memories.processing.encoding_plan import EncodingPlan
from immich_memories.processing.output_contract import (
    InvalidOutputArtifact,
    OutputProbe,
    check_output,
)
from immich_memories.security import configured_secret_values, sanitize_error_message

if TYPE_CHECKING:
    from immich_memories.audio.mood_analyzer import VideoMood
    from immich_memories.audio.music_generator_models import GeneratedMusic, MusicStems
    from immich_memories.config.loader import Config

logger = logging.getLogger(__name__)

# WHY: audio proof decodes the whole supported memory, matching final video validation.
_AUDIO_DECODE_TIMEOUT_SECONDS = 15 * 60


@dataclass(frozen=True, slots=True)
class MusicPhaseResult:
    """Outcome of optional music work without changing artifact validity."""

    applied: bool
    warning: str | None = None


@dataclass(frozen=True, slots=True)
class MusicSelection:
    """The track the run will use, and what it had to settle for to get there.

    The warning travels with the path rather than only reaching the log,
    because a bundled substitution is a success the user still needs told
    about: otherwise a dead backend looks like working music forever.
    """

    path: Path | None
    warning: str | None = None
    stems: MusicStems | None = None


def optional_music_warning(exc: Exception, config: Config | None = None) -> str:
    """Build one user-safe optional-music warning with configured secrets removed."""
    safe_message = sanitize_error_message(str(exc))
    if config is not None:
        for secret in configured_secret_values(config):
            safe_message = safe_message.replace(secret, "***")
    return f"Optional music failed: {safe_message}"


class MusicSource(StrEnum):
    """Which source a run asked for, when it has an opinion.

    ``AUTO`` is the historical precedence and the default: an explicit track,
    else generation when a backend is configured, else the bundle.
    """

    AUTO = "auto"


def music_config_available(config: Config) -> bool:
    """Check if any AI music generation backend is configured and enabled."""
    ace = getattr(config, "ace_step", None)
    mg = getattr(config, "musicgen", None)
    return bool((ace and ace.enabled) or (mg and mg.enabled))


def resolve_music(
    config: Config,
    music_path: Path | None,
    no_music: bool,
    assembly_clips: list[AssemblyClip],
    run_output_dir: Path,
    memory_type: str | None,
    report_fn: Callable[[str, float, str], None] | None = None,
    bundled_library: Path | None = None,
    *,
    transition_overlap: float,
    source: MusicSource = MusicSource.AUTO,
    editorial_attempt_dir: Path | None = None,
    video_duration: float | None = None,
    fps: float = 30,
    work_dir: Path | None = None,
) -> MusicSelection:
    """Determine the music to use: provided path, generated, bundled, or none.

    ``transition_overlap`` is the run's effective crossfade, which both the
    generated and the bundled branch need to read the photo cut cadence off the
    clips (#514). It comes from the run rather than ``config.defaults`` because
    ``--transition`` overrides the configured default.

    ``video_duration`` is the already-assembled film's length. When the caller
    has it, a library track shorter than the film is looped onto itself
    to that length, and generated music is planned to its length (#2472).
    Callers that cannot supply it leave the looping to the mixer and get a
    length estimated from the clips.
    ``work_dir`` holds disposable looped and mastered library files until mixing ends.
    """
    if no_music:
        return MusicSelection(None)
    if music_path is not None:
        # Missing explicit tracks are never silently replaced with bundled music.
        return MusicSelection(music_path if music_path.exists() else None)

    assembly_clips, music_mood, mood_detail = _music_evidence(
        config, assembly_clips, editorial_attempt_dir, memory_type
    )

    warning: str | None = None
    if source is MusicSource.AUTO and music_config_available(config):
        if report_fn:
            report_fn("music", 0.85, "Generating AI music...")
        try:
            generated = auto_generate_music(
                config,
                assembly_clips,
                run_output_dir,
                memory_type,
                report_fn,
                transition_overlap=transition_overlap,
                fps=fps,
                mood_detail=mood_detail,
                video_duration=video_duration,
            )
        except Exception as exc:  # WHY: optional music must not invalidate the base artifact
            # A configured generator that fails used to be worse than no generator
            # at all: the exception unwound past the bundled branch below and the
            # whole music phase was abandoned, so the most-configured setup got
            # the only silent video. Fall through to bundled and carry the warning
            # out with the track — a log line alone never reaches the run artifact,
            # the UI or the nightly notification, so a dead backend stayed invisible.
            warning = optional_music_warning(exc, config)
            generated = None
        if generated:
            return MusicSelection(generated.full_mix, stems=generated.stems)

    # WHY: with no generator configured this used to return silence, which is what
    # the Docker/NAS path gets by default.
    library = _film_music_library(config, music_mood, bundled_library)
    return _resolve_bundled_music(
        music_mood,
        library,
        assembly_clips,
        transition_overlap,
        video_duration,
        work_dir if work_dir is not None else run_output_dir,
        warning,
        fps=fps,
        from_your_folder=library is not None and library == config.audio.local_music_path,
    )


def own_music_available(config: Config) -> bool:
    """Whether your music folder (`audio.local_music_dir`) holds tracks a film can play."""
    from immich_memories.audio.bundled_music import library_has_tracks

    return library_has_tracks(config.audio.local_music_path)


def _film_music_library(config: Config, mood: str | None, bundled: Path | None) -> Path | None:
    """Your own music folder when it has the film's mood, else the bundled library."""
    from immich_memories.audio.bundled_music import bundled_library, music_library_for_mood

    audio = config.audio
    named = audio.local_music_dir != type(audio).model_fields["local_music_dir"].default
    return music_library_for_mood(
        mood,
        audio.local_music_path,
        bundled if bundled is not None else bundled_library(),
        own_library_named=named,
    )


def music_turned_off(config: Config, *, music: str | None, no_music: bool) -> bool:
    """Whether a film plays without music: what the run asked, else ``audio.no_music``.

    One rule for the CLI, the web render panel and automation. ``--no-music`` always
    wins; any ``--music`` (a file, or ``auto``) asks for music despite the config.
    """
    return no_music or (music is None and config.audio.no_music)


def _resolve_bundled_music(
    music_mood: str | None,
    bundled_library: Path | None,
    assembly_clips: list[AssemblyClip],
    transition_overlap: float,
    video_duration: float | None,
    run_output_dir: Path,
    warning: str | None,
    *,
    fps: float = 30,
    from_your_folder: bool = False,
) -> MusicSelection:
    """The library fallback: one track, looped onto itself when the film outlasts it.

    The library is your music folder or the bundle (`_film_music_library`); a warning
    says which one the track came from, never the folder's path. A film never chains
    different tracks: one piece plays from the first frame to the last.
    """
    from immich_memories.audio.bundled_music import bundled_track_for_mood

    where = "a track from your music folder" if from_your_folder else "a bundled track"
    cadence = photo_cadence_seconds(assembly_clips, transition_overlap=transition_overlap, fps=fps)
    # The film's music mood (#2471) picks the folder, so a birthday is not served
    # from the calm one.
    track = bundled_track_for_mood(music_mood, library=bundled_library, cadence_seconds=cadence)
    if track is None:
        if warning:
            missing = "no track in your music folder" if from_your_folder else "no bundled track"
            warning = f"{warning}; {missing} available; no music added"
            logger.warning(warning)
        return MusicSelection(None, warning)
    if video_duration is not None:
        track = _covering(track, video_duration, run_output_dir)
    mastered = _master(track, run_output_dir)
    if warning:
        warning = f"{warning}; used {where} instead"
        logger.warning(warning)
    return MusicSelection(mastered, warning)


def _covering(track: Path, video_duration: float, run_output_dir: Path) -> Path:
    """The track, looped onto itself to the film's length when it is shorter.

    A track the loop cannot read is left as it is; the mixer then loops it
    with a plain crossfade, still the same piece.
    """
    from immich_memories.audio.mixer import get_audio_duration
    from immich_memories.audio.take_join import loop_track

    if get_audio_duration(track) >= video_duration:
        return track
    run_output_dir.mkdir(parents=True, exist_ok=True)
    try:
        return loop_track(track, video_duration, run_output_dir / f"looped_{track.stem}.wav")
    except (subprocess.SubprocessError, OSError, ValueError):
        logger.warning("The library track could not be looped onto itself; the mixer crossfades it")
        return track


def _music_evidence(
    config: Config, clips: list[AssemblyClip], attempt: Path | None, memory_type: str | None
) -> tuple[list[AssemblyClip], str, VideoMood | None]:
    """Apply the film's mood to music copies; preserve facts used by titles and replay.

    Returns the clips, the mood the bundled branch reads, and the reader's full judgment
    the AI branch carries into the caption (energy, tempo, genres) when a model answered.
    Without one the mood comes from the film's own facts (#2471), and its energy is the
    mood's own.
    """
    from immich_memories.audio.film_mood import facts_for_render, read_plan
    from immich_memories.audio.text_mood import mood_for_cut, music_hemisphere

    facts = facts_for_render(
        clips, read_plan(attempt), memory_type=memory_type, hemisphere=music_hemisphere(config)
    )
    choice = asyncio.run(
        mood_for_cut(config, attempt, tuple(clip.asset_id for clip in clips), facts=facts)
    )
    mood = choice.mood.primary_mood
    detail = choice.mood if choice.source == "cut_text" else None
    return [replace(clip, llm_emotion=mood) for clip in clips], mood, detail


def _master(track: Path, run_output_dir: Path) -> Path:
    """Master music we produced. A track the user chose is left as they made it."""
    from immich_memories.audio.mastering import master_music_track

    run_output_dir.mkdir(parents=True, exist_ok=True)
    return master_music_track(track, run_output_dir / f"mastered_{track.stem}.wav")


def transition_overlap_seconds(transition: str, transition_duration: float) -> float:
    """How much a transition shortens the interval between two visible cuts.

    Only a fade overlaps; a hard cut leaves the clips end to end. "smart" is
    counted as a full fade, though it fades at only about 70% of boundaries and
    cuts at the rest (``assembly_engine._pick_transition``), so its overlap is
    the upper bound rather than what every boundary costs.

    The value is subtracted from the median photo duration in
    ``photo_cadence_seconds`` to find how often a photo cut lands, which the
    music selection matches its tempo to.
    """
    return 0.0 if transition in ("cut", "none") else transition_duration


def photo_cadence_seconds(
    assembly_clips: list[AssemblyClip], *, transition_overlap: float, fps: float = 30
) -> float | None:
    """How often a photo cut lands, or None when there is no rhythm to sync to.

    Read off the clips rather than ``config.photos.duration`` because the final
    budget trim rescales every clip: by the time music is chosen, a photo the
    config called 4 s may be 3.7 s on screen. Quantize the clip and overlap
    independently to whole frames at the finished film's ``fps``, then subtract.

    ``transition_overlap`` is not optional on purpose. The cut lands before the
    clip ends: a crossfade starts the next clip at ``duration - fade``, which is
    the clock ``_sequence_frame_counts`` and ``music_mute_windows`` already keep.
    Aligning tempo to the raw duration instead drifted 0.75 beats per photo at
    90 bpm with the default 0.5 s fade (#514), so a caller that has not thought
    about the overlap should not be able to ask for a cadence at all.
    """
    durations = sorted(int(clip.duration * fps) for clip in assembly_clips if clip.is_photo)
    if len(durations) < 2:
        return None
    cadence = (durations[len(durations) // 2] - int(transition_overlap * fps)) / fps
    # A fade wider than the photos themselves leaves no interval to sync to.
    # The assembler downgrades those boundaries to cuts, and the tempo search
    # divides by the cadence, so a zero or negative one is "no rhythm", not 0.
    return cadence if cadence > 0 else None


def auto_generate_music(
    config: Config,
    assembly_clips: list[AssemblyClip],
    run_output_dir: Path,
    memory_type: str | None,
    report_fn: Callable[[str, float, str], None] | None = None,
    *,
    transition_overlap: float,
    fps: float = 30,
    mood_detail: VideoMood | None = None,
    video_duration: float | None = None,
) -> GeneratedMusic | None:
    """Auto-generate music using configured AI backends.

    ``video_duration`` is the assembled film's length; the music is planned
    from it rather than from the clips, whose durations overlap at every
    crossfade (#2472).

    Returns the selected track and stems, or None when no backend
    is available. Backend failures propagate to the optional phase boundary.
    """
    if not music_config_available(config):
        return None

    try:
        from immich_memories.audio.music_generator import generate_music_for_video
        from immich_memories.audio.music_generator_client import MusicGenClientConfig
        from immich_memories.audio.music_generator_models import VideoTimeline
        from immich_memories.audio.text_mood import music_hemisphere
        from immich_memories.audio.track_quality import score_track

        clip_data: list[tuple[float, str, int | None]] = [
            (
                clip.duration,
                clip.llm_emotion or "calm",
                _clip_month_from_date(clip.date),
            )
            for clip in assembly_clips
        ]

        timeline = VideoTimeline.from_clips(
            clips=clip_data,
            title_duration=(
                config.title_screens.title_duration if config.title_screens.enabled else 0
            ),
            ending_duration=(
                config.title_screens.ending_duration if config.title_screens.enabled else 0
            ),
        )
        timeline.film_duration = video_duration

        musicgen_config = MusicGenClientConfig.from_app_config(config.musicgen)
        # One take per film; the periodicity score is logged, never a reason to redo it (#2702).
        musicgen_config.num_versions = 1
        if config.audio.max_regenerations:
            logger.info("audio.max_regenerations is ignored: generated music is one take (#2702)")

        music_dir = run_output_dir / "music"
        music_dir.mkdir(parents=True, exist_ok=True)

        def music_progress(version_idx: int, status: str, progress: float, detail: object) -> None:
            if report_fn:
                report_fn("music", progress / 100.0, f"Music candidate {version_idx + 1}: {status}")

        result = asyncio.run(
            generate_music_for_video(
                timeline=timeline,
                output_dir=music_dir,
                config=musicgen_config,
                progress_callback=music_progress,
                app_config=config,
                hemisphere=music_hemisphere(config),
                memory_type=memory_type,
                photo_cadence_seconds=photo_cadence_seconds(
                    assembly_clips, transition_overlap=transition_overlap, fps=fps
                ),
                mood_detail=mood_detail,
                quality_gate=score_track,
            )
        )

        if result and result.versions:
            result.selected_version = 0
            # The wizard used to do this in its own music path; without it a
            # multi-version generation leaves every rejected take on disk.
            result.cleanup_unselected()
            selected = result.selected
            if selected and selected.full_mix and selected.full_mix.exists():
                logger.info(f"Auto-generated music: {selected.full_mix}")
                return selected

    except (RuntimeError, OSError):
        raise

    return None


def _clip_month_from_date(date_str: str | None) -> int | None:
    """Extract month from a YYYY-MM-DD date string."""
    if not date_str:
        return None
    try:
        return int(date_str.split("-")[1])
    except (IndexError, ValueError):
        return None


def publish_music_mix(
    video_path: Path,
    encoding_plan: EncodingPlan,
) -> OutputProbe:
    """Check the staged music sibling, then atomically replace the film it was mixed from.

    The audio is decoded in full and the container checked against the plan;
    the video, copied from the film, is decoded once later, before the film is
    published. A mix that fails is removed and the film stays as it was.
    """
    staged_path = music_staging_path(video_path, encoding_plan)
    try:
        _require_audio_stream(staged_path)
        probe = check_output(staged_path, encoding_plan)
        staged_path.replace(video_path)
        return probe
    except Exception:
        try:
            staged_path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Music stage cleanup failed; preserving the primary phase outcome")
        raise


@contextmanager
def staged_music_output(video_path: Path, encoding_plan: EncodingPlan) -> Iterator[Path]:
    """Yield a clean container-preserving sibling and remove every leftover."""
    staged_path = music_staging_path(video_path, encoding_plan)
    staged_path.unlink(missing_ok=True)
    try:
        yield staged_path
    finally:
        try:
            staged_path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Music stage cleanup failed; preserving the primary phase outcome")


def _require_audio_stream(path: Path) -> None:
    """Fail closed unless one full audio decode reports positive frame evidence."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-count_frames",
                "-show_entries",
                "stream=codec_type,nb_read_frames",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=_AUDIO_DECODE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise InvalidOutputArtifact("music mix audio validation failed") from exc
    if result.returncode != 0 or result.stderr.strip():
        raise InvalidOutputArtifact("music mix audio decode failed")
    try:
        streams = json.loads(result.stdout).get("streams", [])
        if not streams or streams[0].get("codec_type") != "audio":
            raise InvalidOutputArtifact("music mix is missing audio stream")
        raw_frame_count = streams[0]["nb_read_frames"]
        if not isinstance(raw_frame_count, str) or not raw_frame_count.isdecimal():
            raise InvalidOutputArtifact("music mix has malformed decoded audio frame evidence")
        decoded_frames = int(raw_frame_count)
    except InvalidOutputArtifact:
        raise
    except (AttributeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise InvalidOutputArtifact("music mix is missing decoded audio frame evidence") from exc
    if decoded_frames <= 0:
        raise InvalidOutputArtifact("music mix must have positive decoded audio frames")


def music_staging_path(video_path: Path, encoding_plan: EncodingPlan) -> Path:
    """Return the plan-compatible staged music path or reject a stale base suffix."""
    expected_suffix = f".{encoding_plan.container}"
    if video_path.suffix.lower() != expected_suffix:
        raise ValueError(
            f"Music input suffix {video_path.suffix!r} does not match "
            f"encoding plan container {encoding_plan.container!r}"
        )
    return video_path.with_suffix(f".with_music.{encoding_plan.container}")


def mute_original_audio(video_path: Path, encoding_plan: EncodingPlan) -> OutputProbe:
    """Replace every source recording with silence before music is mixed or a film published."""
    duration = check_output(video_path, encoding_plan).duration_seconds
    with staged_music_output(video_path, encoding_plan) as staged_path:
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    "-i",
                    str(video_path),
                    "-f",
                    "lavfi",
                    "-i",
                    "anullsrc=r=48000:cl=stereo",
                    "-map",
                    "0:v:0",
                    "-map",
                    "1:a:0",
                    "-c:v",
                    "copy",
                    "-c:a",
                    "aac",
                    "-t",
                    str(duration),
                    *CARRY_CONTAINER_METADATA,
                    str(staged_path),
                ],
                capture_output=True,
                check=True,
                timeout=_AUDIO_DECODE_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.SubprocessError):
            # Muting is required output behavior, never an optional-music fallback.
            raise InvalidOutputArtifact(
                "Could not mute original audio; film was not published"
            ) from None
        return publish_music_mix(video_path, encoding_plan)


def apply_music_file(
    video_path: Path,
    music_path: Path,
    volume: float,
    encoding_plan: EncodingPlan,
    mute_windows: list[tuple[float, float]] | None = None,
    *,
    stems: MusicStems | None = None,
) -> OutputProbe:
    """Mix a music file and publish it only when it matches the encoding plan."""
    from immich_memories.audio.mixer import DuckingConfig, MixConfig, mix_audio_with_ducking
    from immich_memories.audio.mixer_helpers import mix_audio_with_4stem_ducking

    mix_config = MixConfig(
        ducking=DuckingConfig(
            music_volume_db=-20 + (volume * 20),
        ),
        mute_windows=mute_windows,
    )
    with staged_music_output(video_path, encoding_plan) as staged_path:
        if (
            stems
            and stems.drums
            and stems.bass
            and stems.other
            and all(p.is_file() for p in (stems.drums, stems.bass, stems.vocals, stems.other))
        ):
            mix_audio_with_4stem_ducking(
                video_path,
                stems.drums,
                stems.bass,
                stems.vocals,
                stems.other,
                staged_path,
                config=mix_config,
            )
        else:
            mix_audio_with_ducking(
                video_path=video_path,
                music_path=music_path,
                output_path=staged_path,
                config=mix_config,
            )
        return publish_music_mix(video_path, encoding_plan)
