"""Title backgrounds encode the decoder's pixel buffers intact."""

import subprocess

import numpy as np
import pytest

from immich_memories.processing.assembly_config import (
    AssemblyClip,
    AssemblySettings,
    standalone_assembly_encoding_plan,
)
from immich_memories.processing.ffmpeg_prober import FFmpegProber
from immich_memories.processing.streaming_frame_decoder import FrameDecoder
from immich_memories.processing.title_background_renderer import TitleBackgroundRenderer
from tests.integration.conftest import requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]


def test_first_clip_background_keeps_pixels_and_one_second_duration(tmp_path):
    source = tmp_path / "white.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=white:size=64x64:rate=4:duration=2",
            "-c:v",
            "ffv1",
            str(source),
        ],
        check=True,
        capture_output=True,
        timeout=20,
    )
    settings = AssemblySettings(encoding_plan=standalone_assembly_encoding_plan())
    renderer = TitleBackgroundRenderer(settings, FFmpegProber(settings))

    output = renderer.render_first_clip([AssemblyClip(source, 2)], tmp_path, 64, 64, 4, None)

    assert output is not None
    frames = list(FrameDecoder(output, 64, 64, 4))
    assert len(frames) == 4
    pixels = np.stack(frames)
    assert np.all(pixels > 230)
