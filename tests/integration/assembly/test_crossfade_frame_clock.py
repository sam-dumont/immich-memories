"""Clip audio follows the frames actually blended, before final padding can hide drift."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from immich_memories.processing.assembly_config import AssemblyClip
from immich_memories.processing.streaming_assembler import assemble_streaming
from immich_memories.processing.streaming_audio import extract_and_mix_audio, mux_video_audio
from tests.integration.conftest import ffprobe_json, requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]


def _sources(directory: Path, fps: float) -> list[Path]:
    paths = [directory / f"source-{index}.mkv" for index in range(2)]
    for index, path in enumerate(paths):
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color={'red' if index else 'blue'}:size=64x64:rate={fps}:duration=1",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={440 + index * 440}:sample_rate=48000:duration=1",
                "-c:v",
                "ffv1",
                "-c:a",
                "pcm_s16le",
                str(path),
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
    return paths


@pytest.mark.parametrize(
    "fps, requested_fade, clip_count",
    [(fps, 0.25, count) for fps in (24, 25, 29.97, 30, 60) for count in (2, 75)] + [(30, 0.01, 2)],
)
def test_audio_overlap_uses_the_video_frame_clock(
    tmp_path: Path, fps: float, requested_fade: float, clip_count: int
) -> None:
    paths = _sources(tmp_path, fps)
    clips = [AssemblyClip(paths[index % 2], 1.0) for index in range(clip_count)]
    transitions = ["fade"] * (clip_count - 1)
    video, audio, film = (tmp_path / name for name in ("video.mp4", "audio.m4a", "film.mp4"))
    assemble_streaming(clips, transitions, video, 64, 64, fps, fade_duration=requested_fade)
    extract_and_mix_audio(
        clips,
        transitions,
        audio,
        fade_duration=requested_fade,
        fps=fps,
        normalize_audio=False,
    )
    mux_video_audio(video, audio, film)
    streams = {stream["codec_type"]: stream for stream in ffprobe_json(film)["streams"]}
    audio_seconds = float(streams["audio"]["duration"])
    video_seconds = float(streams["video"]["duration"])
    expected_overlap = int(requested_fade * fps) / fps
    # MP4 records AAC's last packet duration in milliseconds; tolerate that mux rounding.
    source_seconds = clip_count * int(fps) / fps
    if clip_count == 2:
        assert source_seconds - audio_seconds == pytest.approx(expected_overlap, abs=0.001)
    expected_seconds = source_seconds - (clip_count - 1) * expected_overlap
    assert video_seconds == pytest.approx(expected_seconds, abs=0.001)
    assert audio_seconds == pytest.approx(video_seconds, abs=1 / fps)
