"""run_music_phase tells resolve_music the already-assembled film's length.

#2070: the bundled-music playlist needs the film's duration to decide between
a single track and a varied, crossfaded sequence. Before this, nothing
upstream of the bundled branch knew the final runtime at all.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

from immich_memories.config_loader import Config
from immich_memories.generate import GenerationParams
from immich_memories.generate_music import MusicSelection
from immich_memories.generate_settings import run_music_phase
from immich_memories.processing.encoding_plan import EncodingPlan, HdrTransfer, OutputCodec


def _h264_plan() -> EncodingPlan:
    return EncodingPlan(
        codec=OutputCodec.H264,
        encoder="libx264",
        encoder_args=("-c:v", "libx264"),
        target_transfer=HdrTransfer.NONE,
        tone_map_to_sdr=False,
        pixel_format="yuv420p",
        container="mp4",
    )


def _real_video(path: Path, duration: float) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=black:s=32x32:r=5:d={duration}",
            str(path),
        ],
        check=True,
    )


def test_the_assembled_videos_length_reaches_resolve_music(tmp_path: Path, monkeypatch) -> None:
    video = tmp_path / "result.mp4"
    _real_video(video, 5.0)

    seen: list[float | None] = []

    def _fake_resolve(**kwargs):
        seen.append(kwargs.get("video_duration"))
        return MusicSelection(None)

    monkeypatch.setattr("immich_memories.generate_music.resolve_music", _fake_resolve)

    run_music_phase(
        GenerationParams(clips=[], output_path=video, config=Config()),
        [],
        video,
        tmp_path,
        MagicMock(),
        encoding_plan=_h264_plan(),
    )

    assert seen and seen[0] is not None
    assert 4.5 <= seen[0] <= 5.5


def test_an_unreadable_result_path_passes_no_duration_rather_than_raising(
    tmp_path: Path, monkeypatch
) -> None:
    """The music phase is optional; a probe failure must not abort it."""
    missing = tmp_path / "missing.mp4"

    seen: list[float | None] = []

    def _fake_resolve(**kwargs):
        seen.append(kwargs.get("video_duration"))
        return MusicSelection(None)

    monkeypatch.setattr("immich_memories.generate_music.resolve_music", _fake_resolve)

    run_music_phase(
        GenerationParams(clips=[], output_path=missing, config=Config()),
        [],
        missing,
        tmp_path,
        MagicMock(),
        encoding_plan=_h264_plan(),
    )

    assert seen == [None]
