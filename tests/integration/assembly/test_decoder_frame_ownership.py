"""Borrowed streaming frames must not weaken the ordinary iterator's ownership."""

import subprocess
from contextlib import closing

import numpy as np
import pytest

from immich_memories.processing.streaming_frame_decoder import FrameDecoder
from tests.integration.conftest import requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]


@pytest.fixture
def moving_source(tmp_path):
    source = tmp_path / "moving.mkv"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=64x64:rate=4:duration=1",
            "-c:v",
            "ffv1",
            str(source),
        ],
        check=True,
        capture_output=True,
        timeout=20,
    )
    return source


@pytest.mark.parametrize("pix_fmt", ["rgb24", "yuv420p10le"])
def test_borrowed_frames_reuse_storage_and_match_owned_pixels(moving_source, pix_fmt):
    decoder = FrameDecoder(moving_source, 64, 64, 4, pix_fmt=pix_fmt, source_size=(64, 64))
    owned = list(decoder)
    assert len(owned) == 4
    assert not np.array_equal(owned[0], owned[1])

    with closing(decoder.iter_borrowed_frames()) as frames:
        first = next(frames)
        saved = first.copy()
        second = next(frames)
        # Two slots keep the latest complete frame safe from an incomplete read.
        assert not np.shares_memory(first, second)
        assert not second.flags.writeable
        np.testing.assert_array_equal(saved, owned[0])
        np.testing.assert_array_equal(second, owned[1])
        third = next(frames)
        assert np.shares_memory(first, third)
        remaining = [third.copy(), *[frame.copy() for frame in frames]]

    for actual, expected in zip(remaining, owned[2:], strict=True):
        np.testing.assert_array_equal(actual, expected)
    # The independent iterator's retained frames survived all subsequent reads.
    np.testing.assert_array_equal(owned[0], saved)


def test_streaming_assembly_borrows_frames_for_synchronous_encoder_writes(
    moving_source, tmp_path, monkeypatch
):
    from immich_memories.processing.assembly_config import AssemblyClip
    from immich_memories.processing.encoding_plan import EncodingPlan, HdrTransfer, OutputCodec
    from immich_memories.processing.streaming_assembler import StreamingEncoder, assemble_streaming

    written = []
    original_write = StreamingEncoder.write_frame

    def record_write(encoder, frame):
        written.append(frame)
        original_write(encoder, frame)

    # WHY: Observe the encoder WRITE boundary; decoding and encoding both stay real.
    monkeypatch.setattr(StreamingEncoder, "write_frame", record_write)
    plan = EncodingPlan(
        OutputCodec.H264,
        "libx264",
        ("-preset", "ultrafast", "-crf", "18"),
        HdrTransfer.NONE,
        False,
        "yuv420p",
        "mp4",
    )
    assemble_streaming(
        [AssemblyClip(moving_source, 1)],
        [],
        tmp_path / "assembled.mp4",
        64,
        64,
        4,
        encoding_plan=plan,
    )
    assert len(written) == 4
    assert np.shares_memory(written[0], written[2])
    assert np.shares_memory(written[1], written[3])
    assert not np.shares_memory(written[0], written[1])


@pytest.mark.parametrize("pix_fmt", ["rgb24", "yuv420p10le"])
def test_incomplete_final_write_preserves_the_last_complete_borrowed_frame(
    moving_source, tmp_path, monkeypatch, pix_fmt
):
    import os
    import shutil
    import sys

    decoder = FrameDecoder(moving_source, 64, 64, 4, pix_fmt=pix_fmt, source_size=(64, 64))
    expected = list(decoder)
    real_ffmpeg = shutil.which("ffmpeg")
    assert real_ffmpeg is not None
    wrapper = tmp_path / "ffmpeg"
    # WHY: Fault-inject only the external producer's WRITE. Real FFmpeg still
    # decodes the source, but the wrapper terminates halfway through frame 3.
    wrapper.write_text(
        f"#!{sys.executable}\n"
        "import subprocess, sys\n"
        f"proc = subprocess.Popen([{real_ffmpeg!r}, *sys.argv[1:]], "
        "stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)\n"
        f"sys.stdout.buffer.write(proc.stdout.read({64 * 64 * 3 * 5 // 2}))\n"
        "proc.stdout.close()\n"
        "if proc.poll() is None: proc.terminate()\n"
        "proc.wait(timeout=5)\n"
    )
    wrapper.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])

    with closing(decoder.iter_borrowed_frames()) as frames:
        next(frames)
        last_complete = next(frames)
        np.testing.assert_array_equal(last_complete, expected[1])
        with pytest.raises(StopIteration):
            next(frames)
        np.testing.assert_array_equal(last_complete, expected[1])
