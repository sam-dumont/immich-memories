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
@pytest.mark.parametrize("read_ahead", [False, True])
def test_borrowed_frames_reuse_storage_and_match_owned_pixels(moving_source, pix_fmt, read_ahead):
    decoder = FrameDecoder(moving_source, 64, 64, 4, pix_fmt=pix_fmt, source_size=(64, 64))
    owned = list(decoder)
    assert len(owned) == 4
    assert not np.array_equal(owned[0], owned[1])

    with closing(decoder.iter_borrowed_frames(read_ahead=read_ahead)) as frames:
        first = next(frames)
        saved = first.copy()
        second = next(frames)
        # Two slots keep the latest complete frame safe from an incomplete read.
        assert not np.shares_memory(first, second)
        assert not second.flags.writeable
        np.testing.assert_array_equal(saved, owned[0])
        np.testing.assert_array_equal(second, owned[1])
        third = next(frames)
        assert np.shares_memory(first, third) is not read_ahead
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
@pytest.mark.parametrize("read_ahead", [False, True])
def test_incomplete_final_write_preserves_the_last_complete_borrowed_frame(
    moving_source, tmp_path, monkeypatch, pix_fmt, read_ahead
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

    with closing(decoder.iter_borrowed_frames(read_ahead=read_ahead)) as frames:
        next(frames)
        last_complete = next(frames)
        np.testing.assert_array_equal(last_complete, expected[1])
        with pytest.raises(StopIteration):
            next(frames)
        np.testing.assert_array_equal(last_complete, expected[1])


def test_encoder_failure_reaps_decoder_even_with_a_retained_traceback(
    moving_source, tmp_path, monkeypatch
):
    from immich_memories.processing.assembly_config import AssemblyClip
    from immich_memories.processing.encoding_plan import EncodingPlan, HdrTransfer, OutputCodec
    from immich_memories.processing.streaming_assembler import StreamingEncoder, assemble_streaming

    decoders = []
    real_popen = subprocess.Popen

    def observe_start(cmd, **kwargs):
        process = real_popen(cmd, **kwargs)
        if "pipe:1" in cmd and "rawvideo" in cmd:
            decoders.append(process)
        return process

    def reject_write(_encoder, _frame):
        raise RuntimeError("encoder rejected a frame")

    # WHY: Observe real child creation so a leaked decoder cannot hide behind a mock.
    monkeypatch.setattr(subprocess, "Popen", observe_start)
    # WHY: Fail only the sink's WRITE; source probing and decoding remain real.
    monkeypatch.setattr(StreamingEncoder, "write_frame", reject_write)
    plan = EncodingPlan(
        OutputCodec.H264,
        "libx264",
        ("-preset", "ultrafast"),
        HdrTransfer.NONE,
        False,
        "yuv420p",
        "mp4",
    )
    try:
        with pytest.raises(RuntimeError, match="encoder rejected") as failure:
            assemble_streaming(
                [AssemblyClip(moving_source, 1)],
                [],
                tmp_path / "failed.mp4",
                512,
                512,
                4,
                encoding_plan=plan,
            )
        assert failure.value.__traceback__ is not None
        assert decoders
        assert all(process.poll() is not None for process in decoders)
    finally:
        for process in decoders:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)


@pytest.mark.parametrize(("gib", "cpus", "slots"), [(4, 4, 2), (3, 4, 2), (4, 1, 2)])
def test_software_assembly_keeps_synchronous_reads_with_any_resource_budget(
    moving_source, tmp_path, monkeypatch, gib, cpus, slots
):
    from immich_memories.processing import memory_budget
    from immich_memories.processing.assembly_config import AssemblyClip
    from immich_memories.processing.encoding_plan import EncodingPlan, HdrTransfer, OutputCodec
    from immich_memories.processing.streaming_assembler import StreamingEncoder, assemble_streaming

    cgroup = tmp_path / "cgroup"
    cgroup.mkdir()
    (cgroup / "memory.max").write_text(str(gib * 2**30))
    (cgroup / "cpu.max").write_text(f"{cpus * 100000} 100000")
    # WHY: Read actual resource files under an isolated cgroup root, not mocked budgets.
    monkeypatch.setattr(memory_budget, "_CGROUP", cgroup)
    written = []
    original_write = StreamingEncoder.write_frame

    def record_write(encoder, frame):
        written.append(frame)
        original_write(encoder, frame)

    # WHY: Observe the real encoder WRITE boundary; all reads and encoding stay real.
    monkeypatch.setattr(StreamingEncoder, "write_frame", record_write)
    plan = EncodingPlan(
        OutputCodec.H264,
        "libx264",
        ("-preset", "ultrafast"),
        HdrTransfer.NONE,
        False,
        "yuv420p",
        "mp4",
    )
    assemble_streaming(
        [AssemblyClip(moving_source, 1)],
        [],
        tmp_path / "large.mp4",
        1920,
        1080,
        4,
        encoding_plan=plan,
    )
    assert len(written) == 4
    assert len({frame.__array_interface__["data"][0] for frame in written}) == slots
