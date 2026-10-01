"""Discarded source frames must not pay for output-resolution filtering."""

import subprocess
from fractions import Fraction

import pytest

from immich_memories.processing.streaming_frame_decoder import FrameDecoder
from tests.integration.conftest import requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]


def test_discarded_frames_do_not_reach_the_scaler(tmp_path):
    decoder = FrameDecoder(
        tmp_path / "source.mkv",
        256,
        144,
        30,
        source_size=(128, 72),
        source_frame_rate=Fraction(120),
    )
    # Real FFmpeg's bench filter counts executions at the expensive operation,
    # including source frames that disappear before the output stream.
    chain = decoder._build_vf().replace("scale=", "bench=start,scale=", 1)
    chain = chain.replace(":flags=lanczos", ":flags=lanczos,bench=stop", 1)
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-loglevel",
            "repeat+info",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=128x72:rate=120:duration=1",
            "-vf",
            chain,
            "-an",
            "-f",
            "framemd5",
            "pipe:1",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    frames = [line for line in result.stdout.splitlines() if line.startswith("0,")]
    scaled = [line for line in result.stderr.splitlines() if "bench" in line and " t:" in line]
    assert len(frames) == 30
    assert len(scaled) == 30
