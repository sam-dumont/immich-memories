"""A decoder closed before its last frame ends FFmpeg without waiting out SIGTERM (#2709).

FFmpeg blocked writing to a full pipe never sees SIGTERM, so an early stop used
to wait the whole terminate grace and then SIGKILL it, once per film for the
title's first-clip background.
"""

import signal
import subprocess
from contextlib import closing

import pytest

from immich_memories.processing import streaming_frame_decoder
from immich_memories.processing.streaming_frame_decoder import FrameDecoder
from tests.integration.conftest import requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]


@pytest.fixture
def long_source(tmp_path):
    # 256x256 rgb24 frames are three times a pipe's buffer, and 20 s of them are
    # far more than the two frames the test reads.
    source = tmp_path / "long.mkv"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-f", "lavfi",
            "-i", "testsrc2=size=256x256:rate=30:duration=20",
            "-c:v", "ffv1", str(source),
        ],
        check=True, capture_output=True, timeout=60,
    )  # fmt: skip
    return source


@pytest.mark.parametrize("read_ahead", [False, True])
def test_an_early_close_ends_ffmpeg_without_sigkill(long_source, monkeypatch, read_ahead):
    stopped: list[subprocess.Popen] = []
    real_stop = streaming_frame_decoder.stop_owned_process

    def recording_stop(process, **kwargs):
        stopped.append(process)
        real_stop(process, **kwargs)

    # WHY: a spy on the stop boundary, to read how the real FFmpeg ended.
    monkeypatch.setattr(streaming_frame_decoder, "stop_owned_process", recording_stop)
    decoder = FrameDecoder(long_source, 256, 256, 30, source_size=(256, 256))

    with closing(decoder.iter_borrowed_frames(read_ahead=read_ahead)) as frames:
        next(frames)
        next(frames)

    assert len(stopped) == 1
    assert stopped[0].returncode is not None
    assert stopped[0].returncode != -signal.SIGKILL
