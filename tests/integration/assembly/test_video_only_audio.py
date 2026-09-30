"""A video without an audio track still contributes its picture and silent time."""

import subprocess
from fractions import Fraction

import pytest

from immich_memories.processing.assembly_config import (
    AssemblyClip,
    AssemblySettings,
    TransitionType,
    standalone_assembly_encoding_plan,
)
from immich_memories.processing.video_assembler import VideoAssembler
from tests.integration.conftest import ffprobe_json, requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]


@pytest.mark.parametrize("privacy_mode", [False, True])
@pytest.mark.parametrize("clip_count", [1, 2])
def test_video_only_source_survives_assembly(tmp_path, caplog, privacy_mode, clip_count):
    source = tmp_path / "muted.mp4"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
            "color=red:s=320x180:r=30:d=0.5", "-c:v", "libx264", "-an", str(source),
        ], check=True, capture_output=True,
    )  # fmt: skip
    settings = AssemblySettings(
        encoding_plan=standalone_assembly_encoding_plan(23),
        target_resolution=(320, 180),
        transition=TransitionType.CUT,
        privacy_mode=privacy_mode,
        scale_mode="fit",
    )
    output = VideoAssembler(settings).assemble(
        [AssemblyClip(path=source, duration=0.5)] * clip_count, tmp_path / "film.mp4"
    )
    streams = ffprobe_json(output)["streams"]
    video = next(stream for stream in streams if stream["codec_type"] == "video")
    expected_frames = int(Fraction(video["avg_frame_rate"]) * clip_count / 2)
    assert int(video["nb_frames"]) == expected_frames
    assert any(stream["codec_type"] == "audio" for stream in streams)
    pixels = subprocess.check_output([
        "ffmpeg", "-v", "error", "-i", str(output), "-vf", "scale=1:1",
        "-pix_fmt", "rgb24", "-f", "rawvideo", "-",
    ])  # fmt: skip
    assert len(pixels) == expected_frames * 3
    assert min(pixels[::3]) > 200
    assert "Frame underrun" not in caplog.text
