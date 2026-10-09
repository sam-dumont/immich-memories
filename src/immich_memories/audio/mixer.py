"""Audio mixing with intelligent ducking and music looping."""

from __future__ import annotations

import contextlib
import logging
import math
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from immich_memories.delivery_timestamp import CARRY_CONTAINER_METADATA
from immich_memories.security import validate_audio_path, validate_video_path

logger = logging.getLogger(__name__)


# #1954: a FULL-tier film's 4-stem amix (normalize=0, so it can clip) only had
# a 0.95 sample-peak limiter ahead of AAC encoding (-0.45 dBFS of headroom).
# AAC reconstruction rings past a limiter that only capped sample peaks, so the
# decoded file measured +1.73 dBFS. Oversampling before the limiter approximates
# a true-peak limit, and -2 dBFS leaves room for the encoder's own overshoot.
_FINAL_MIX_CEILING_DB = -2.0


def final_mix_safety_filter(ceiling_db: float = _FINAL_MIX_CEILING_DB) -> str:
    """FFmpeg filter fragment: a true-peak-safe ceiling for a finished mix.

    Every mixer's final amix must pass its [mixed] stream through this before
    the AAC encode — chain it in with no input/output labels of its own.

    WHY latency=1: alimiter's lookahead otherwise delays every sample by its
    own buffer without reporting it, so a transition that happens at 1.000s
    landed at 1.004958s measured — audible drift on hard cuts. latency=1
    compensates the delay (FFmpeg >=5.0; this project's floor is 5.1).
    """
    limit = 10 ** (ceiling_db / 20)
    return (
        f"aresample=192000,alimiter=limit={limit:.4f}:level=disabled:attack=5:release=50:"
        "latency=1,aresample=48000"
    )


def _db_to_linear(db: float, min_val: float = 1.0, max_val: float = 64.0) -> float:
    """Convert dB to linear scale for FFmpeg parameters.

    FFmpeg's sidechaincompress 'makeup' parameter expects linear scale (1-64).
    Formula: linear = 10^(dB/20)

    Args:
        db: Value in decibels
        min_val: Minimum allowed linear value
        max_val: Maximum allowed linear value

    Returns:
        Linear value clamped to [min_val, max_val]
    """
    linear = 10 ** (db / 20)
    return max(min_val, min(max_val, linear))


@dataclass
class DuckingConfig:
    """Configuration for audio ducking (lowering music when speech is present)."""

    # Threshold for sidechain compression (0.0-1.0)
    # Lower values = more sensitive to speech
    threshold: float = 0.02

    # Compression ratio (how much to lower music)
    # Higher = more aggressive ducking (4.0 = moderate, smoother than 6.0)
    ratio: float = 4.0

    # Attack time in milliseconds (how fast ducking kicks in)
    # 100ms = smooth fade down, not too abrupt
    attack_ms: float = 100.0

    # Release time in milliseconds (how fast music comes back)
    # 2500ms = music stays ducked during natural speech pauses (word -> pause -> word)
    # This prevents the "pumping" effect between words
    release_ms: float = 2500.0

    # Makeup gain in dB (boost after compression)
    makeup_db: float = 0.0

    # Music volume reduction in dB (base level before ducking)
    music_volume_db: float = -6.0


@dataclass
class MixConfig:
    """Configuration for audio mixing."""

    ducking: DuckingConfig
    fade_in_seconds: float = 2.0
    fade_out_seconds: float = 3.0
    music_starts_at: float = 0.0  # Seconds into video
    normalize_audio: bool = True
    # Timeline windows [start, end) where the source audio IS music and the
    # soundtrack must step aside (#466) — near-mute, not sidechain-lowered.
    mute_windows: list[tuple[float, float]] | None = None


def get_audio_duration(audio_path: Path) -> float:
    """Get the duration of an audio file in seconds.

    Args:
        audio_path: Path to the audio file

    Returns:
        Duration in seconds
    """
    # Validate path before subprocess call
    validated_path = validate_audio_path(audio_path, must_exist=True)
    return _get_duration_unchecked(validated_path)


def get_video_duration(video_path: Path) -> float:
    """Get the duration of a video file in seconds.

    Args:
        video_path: Path to the video file

    Returns:
        Duration in seconds
    """
    # Validate as video, then use audio duration probe (same ffprobe command)
    validated_path = validate_video_path(video_path, must_exist=True)
    # Re-use the audio duration function with validated path
    return _get_duration_unchecked(validated_path)


def _get_duration_unchecked(path: Path) -> float:
    """Get duration without validation (internal use after validation)."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError) as e:
        logger.error(f"Could not get duration: {e}")
        return 0.0


def plan_loop_copies(*, audio_duration: float, target_duration: float, crossfade: float) -> int:
    """How many copies of a track are needed to cover ``target_duration``.

    Consecutive copies overlap by ``crossfade`` seconds, so each repeat adds
    ``audio_duration - crossfade``, not the full track length.
    """
    if audio_duration >= target_duration:
        return 1
    # A crossfade cannot be longer than the track it joins.
    effective = max(audio_duration - min(crossfade, audio_duration / 2), 0.01)
    return max(2, math.ceil((target_duration - audio_duration) / effective) + 1)


# Below this, a generated block's lead-in/tail reads as silence rather than music.
_BLOCK_SILENCE_THRESHOLD_DB = -50.0
# How much of that near-silence to leave in place: enough that a trim never
# reads as an abrupt cut, short enough that it cannot hold a seam open.
_BLOCK_SILENCE_KEEP_SECONDS = 0.2


def _trim_block_silence(source: Path, destination: Path) -> Path | None:
    """Trim a block's near-silent lead-in/tail before it can hold open a seam.

    ACE-Step blocks often end (sometimes start) with several seconds below
    -50 dB. assemble_music chains blocks with a crossfade, so an untrimmed
    block can land a multi-second near-silent stretch right at that seam
    (#1954). Falls back to the source on a trim failure — a seam defect is
    better than a missing block. Returns None when the block was near-silent
    throughout: keeping its untrimmed self in the chain would reintroduce
    the exact gap this trim exists to close, so the caller drops it instead.

    WHY two single-sided passes, not one stop_periods=1 pass: silenceremove's
    stop side cuts at the FIRST sub-threshold stretch after sound starts, not
    only at the end — a quiet internal pause or bridge would chop the block
    down to its opening phrase. Reversing for the tail pass keeps both ends
    single-sided.
    """
    command = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-i",
        str(source),
        "-af",
        f"silenceremove=start_periods=1:start_threshold={_BLOCK_SILENCE_THRESHOLD_DB}dB:"
        "start_silence=0.05,"
        f"areverse,silenceremove=start_periods=1:start_threshold={_BLOCK_SILENCE_THRESHOLD_DB}dB:"
        f"start_silence={_BLOCK_SILENCE_KEEP_SECONDS},areverse",
        str(destination),
    ]
    try:
        subprocess.run(command, capture_output=True, check=True, timeout=120)
    except (subprocess.SubprocessError, OSError) as error:
        logger.warning("Block silence trim failed, using the block untrimmed: %s", error)
        return source
    # A block that was near-silent throughout can trim away to nothing.
    if get_audio_duration(destination) <= 0.05:
        return None
    return destination


def assemble_music(
    block_paths: list[Path],
    target_duration: float,
    output_path: Path,
    crossfade_seconds: float = 2.0,
) -> Path:
    """Fold a sequence of distinct blocks into one track of ``target_duration``.

    The block sequence repeats (crossfaded, then trimmed) until it covers the
    target, so a long video gets several different takes of the same style rather
    than one phrase on repeat. Output is PCM WAV so mastering and ducking re-encode
    a clean source, unlike the mp3 ``loop_audio_to_duration`` writes for final
    delivery. Each block's near-silent lead-in/tail is trimmed first, so a seam
    never lands on a multi-second silent stretch.
    """
    if not block_paths:
        raise ValueError("assemble_music needs at least one block")
    trimmed = [
        _trim_block_silence(path, output_path.parent / f"{output_path.stem}_trim{i}.wav")
        for i, path in enumerate(block_paths)
    ]
    kept = [path for path in trimmed if path is not None]
    if not kept:
        logger.warning(
            "All %d music blocks were near-silent throughout; keeping them "
            "untrimmed rather than losing the track entirely",
            len(block_paths),
        )
        kept = block_paths
    block_paths = kept
    durations = [get_audio_duration(p) for p in block_paths]
    shortest = min(durations)
    fade = min(crossfade_seconds, max(shortest / 2, 0.01))
    # One pass through the sequence, after the overlaps between its blocks.
    once = max(sum(durations) - fade * (len(durations) - 1), 0.01)
    # Each further pass adds (once - fade): its first block crossfades into the
    # previous pass's last block. Fold the block sequence until the target is met.
    if once - fade > 0.01:
        copies = max(1, math.ceil((target_duration - fade) / (once - fade)))
    else:  # degeneration: every block is shorter than the crossfade
        copies = max(1, math.ceil(target_duration / once))

    inputs = block_paths * copies
    chain = []
    previous = "0:a"
    for index in range(1, len(inputs)):
        label = f"x{index}"
        chain.append(f"[{previous}][{index}:a]acrossfade=d={fade}:c1=tri:c2=tri[{label}]")
        previous = label

    fade_out_start = max(target_duration - 2, 0)
    chain.append(
        f"[{previous}]atrim=0:{target_duration},"
        f"afade=t=in:st=0:d=1,afade=t=out:st={fade_out_start}:d=2[out]"
    )

    cmd = ["ffmpeg", "-y"]
    for path in inputs:
        cmd += ["-i", str(path)]
    cmd += ["-filter_complex", ";".join(chain), "-map", "[out]", str(output_path)]
    subprocess.run(cmd, capture_output=True, check=True, timeout=600)
    return output_path


def loop_audio_to_duration(
    audio_path: Path,
    target_duration: float,
    output_path: Path | None = None,
    crossfade_seconds: float = 2.0,
) -> Path:
    """Loop an audio file to reach target duration with crossfade.

    Args:
        audio_path: Path to the source audio
        target_duration: Target duration in seconds
        output_path: Output path (auto-generated if None)
        crossfade_seconds: Crossfade duration between loops

    Returns:
        Path to the looped audio file
    """
    if output_path is None:
        # Use NamedTemporaryFile for secure temp file creation (no race condition)
        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", prefix="looped_", delete=False)
        tmp.close()
        output_path = Path(tmp.name)

    audio_duration = get_audio_duration(audio_path)

    if audio_duration <= 0:
        raise ValueError(f"Could not determine duration of {audio_path}")

    # If audio is already long enough, just trim it
    if audio_duration >= target_duration:
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(audio_path),
            "-t",
            str(target_duration),
            "-acodec",
            "libmp3lame",
            "-q:a",
            "2",
            str(output_path),
        ]
        subprocess.run(cmd, capture_output=True, check=True, timeout=600)
        return output_path

    copies = plan_loop_copies(
        audio_duration=audio_duration,
        target_duration=target_duration,
        crossfade=crossfade_seconds,
    )
    # A crossfade cannot be longer than half the track it joins on either side.
    fade = min(crossfade_seconds, audio_duration / 2)

    # WHY: acrossfade joins two streams, so the track is opened once per copy and
    # the copies are folded together pairwise. Without this the loop is a butt
    # splice and every repeat clicks.
    chain = []
    previous = "0:a"
    for index in range(1, copies):
        label = f"x{index}"
        chain.append(f"[{previous}][{index}:a]acrossfade=d={fade}:c1=tri:c2=tri[{label}]")
        previous = label

    fade_out_start = max(target_duration - 2, 0)
    chain.append(
        f"[{previous}]atrim=0:{target_duration},"
        f"afade=t=in:st=0:d=1,afade=t=out:st={fade_out_start}:d=2[out]"
    )

    cmd = ["ffmpeg", "-y"]
    for _ in range(copies):
        cmd += ["-i", str(audio_path)]
    cmd += [
        "-filter_complex",
        ";".join(chain),
        "-map",
        "[out]",
        "-acodec",
        "libmp3lame",
        "-q:a",
        "2",
        str(output_path),
    ]

    try:
        subprocess.run(cmd, capture_output=True, check=True, timeout=600)
    except subprocess.CalledProcessError as e:
        logger.error(f"Loop failed: {e.stderr.decode() if e.stderr else e}")
        raise

    return output_path


def mix_audio_with_ducking(
    video_path: Path,
    music_path: Path,
    output_path: Path,
    config: MixConfig | None = None,
) -> Path:
    """Mix background music with video, ducking music when speech is present.

    Uses FFmpeg's sidechaincompress filter to automatically lower music
    volume when the video's audio is louder (speech, sound effects, etc.).

    Args:
        video_path: Path to the video file
        music_path: Path to the background music
        output_path: Path for the output video
        config: Mixing configuration

    Returns:
        Path to the output video
    """
    if config is None:
        config = MixConfig(ducking=DuckingConfig())

    ducking = config.ducking
    video_duration = get_video_duration(video_path)

    # First, ensure music is long enough
    music_duration = get_audio_duration(music_path)
    music_to_use = music_path

    if music_duration < video_duration:
        logger.info(f"Looping music from {music_duration:.1f}s to {video_duration:.1f}s")
        # Use NamedTemporaryFile for secure temp file creation (no race condition)
        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", prefix="looped_music_", delete=False)
        tmp.close()
        looped_music = Path(tmp.name)
        music_to_use = loop_audio_to_duration(music_path, video_duration, looped_music)

    # Build the complex filter for ducking
    filter_parts = _build_ducking_filter(config, ducking, video_duration)
    filter_complex = ";".join(filter_parts)

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-i",
        str(music_to_use),
        "-filter_complex",
        filter_complex,
        "-map",
        "0:v",  # Keep original video
        "-map",
        "[mixed]",  # Use mixed audio
        "-c:v",
        "copy",  # Don't re-encode video
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        *CARRY_CONTAINER_METADATA,
        str(output_path),
    ]

    try:
        logger.info("Mixing audio with ducking...")
        subprocess.run(cmd, capture_output=True, check=True, timeout=600)
        logger.info(f"Audio mixed successfully: {output_path}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Audio mixing failed: {e.stderr.decode() if e.stderr else e}")
        raise
    finally:
        # Cleanup looped music if we created it
        if music_to_use != music_path and music_to_use.exists():
            with contextlib.suppress(OSError):
                music_to_use.unlink()

    return output_path


def _build_ducking_filter(
    config: MixConfig, ducking: DuckingConfig, video_duration: float
) -> list[str]:
    """Build FFmpeg filter parts for audio ducking."""
    filter_parts = []

    # Prepare music: trim to video length, apply volume, add fades
    music_filter = f"[1:a]atrim=0:{video_duration}"
    music_filter += f",volume={ducking.music_volume_db}dB"
    # WHY 0.05 not 0: dead silence reads as an error; -26 dB reads as stepping
    # aside. The step lands on a clip boundary, where the cut masks it.
    for start, end in config.mute_windows or []:
        music_filter += f",volume=enable='between(t,{start},{end})':volume=0.05"

    if config.fade_in_seconds > 0:
        music_filter += f",afade=t=in:st={config.music_starts_at}:d={config.fade_in_seconds}"

    if config.fade_out_seconds > 0:
        fade_start = video_duration - config.fade_out_seconds
        music_filter += f",afade=t=out:st={fade_start}:d={config.fade_out_seconds}"

    music_filter += "[music]"
    filter_parts.append(music_filter)

    # Prepare video audio (normalize if requested)
    # WHY: Split into two copies — FFmpeg 6.x doesn't allow consuming a label twice.
    # [va] feeds sidechaincompress (as sidechain input), [vamix] feeds amix.
    # WHY: apad+atrim forces audio to exact video duration. The mux step before
    # this already pads, but some FFmpeg versions/codecs don't honor padded AAC
    # duration on re-decode — the stream decodes shorter than container metadata.
    pad = f"apad=whole_dur={video_duration},atrim=0:{video_duration},"
    if config.normalize_audio:
        # Resample loudnorm's large 192 kHz blocks before the FFmpeg 6/7 sidechain.
        filter_parts.append(
            f"[0:a]{pad}loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000,asplit=2[va][vamix]"
        )
    else:
        filter_parts.append(f"[0:a]{pad}asplit=2[va][vamix]")

    # Apply sidechain compression: duck music when video audio is present
    sidechain_filter = (
        f"[music][va]sidechaincompress="
        f"threshold={ducking.threshold}:"
        f"ratio={ducking.ratio}:"
        f"attack={ducking.attack_ms}:"
        f"release={ducking.release_ms}:"
        f"makeup={_db_to_linear(ducking.makeup_db):.2f}"
        f"[ducked_music]"
    )
    filter_parts.extend(
        (
            sidechain_filter,
            # WHY: duration=longest + final apad/atrim = belt-and-suspenders for
            # correct output duration. amix duration=longest should produce full
            # length, but some FFmpeg versions write incorrect stream duration
            # metadata. The final apad/atrim guarantees both the actual samples
            # AND the metadata match video_duration.
            # WHY normalize=0: amix defaults to scaling inputs down so a 2-input
            # sum cannot clip, which measured 6 dB quieter on equal-level tones
            # (#2070) — the bundled-music path only ran through this function and
            # landed at -29 to -35 dBFS against generated music's -21 to -24,
            # because mix_audio_with_4stem_ducking already sets normalize=0 and
            # leaves the limiter below to guard the ceiling instead.
            "[vamix][ducked_music]amix=inputs=2:duration=longest:"
            "dropout_transition=2:normalize=0,"
            f"{final_mix_safety_filter()},"
            f"apad=whole_dur={video_duration},atrim=0:{video_duration}[mixed]",
        )
    )

    return filter_parts


def music_mute_windows(
    clips: list,
    transitions: list[str],
    fade_duration: float,
    *,
    fps: float = 30,
) -> list[tuple[float, float]]:
    """Timeline windows of clips whose own audio is music (#466).

    Count whole clip and overlap frames, just as the assembler does, before
    converting to seconds. Adjacent music windows merge so
    the soundtrack does not pump between back-to-back concert clips.
    """
    windows: list[tuple[int, int]] = []
    fade_frames = int(fade_duration * fps)
    start = 0
    for idx, clip in enumerate(clips):
        if idx > 0 and idx - 1 < len(transitions) and transitions[idx - 1] == "fade":
            start -= fade_frames
        end = start + int(clip.duration * fps)
        if getattr(clip, "has_music", False):
            if windows and start <= windows[-1][1]:
                windows[-1] = (windows[-1][0], end)
            else:
                windows.append((start, end))
        start = end
    return [(start / fps, end / fps) for start, end in windows]
