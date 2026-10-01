"""HDR source buffers survive decoder advances and crossfade scratch reuse."""

from __future__ import annotations

import io
from types import SimpleNamespace

import numpy as np

from immich_memories.processing.streaming_frame_blender import FrameBlender
from immich_memories.processing.streaming_frame_decoder import FrameDecoder


def test_held_hdr_frames_keep_samples_after_decode_and_crossfade(monkeypatch, tmp_path):
    samples = [
        np.array([64, 120, 500, 940, 512, 512], dtype=np.uint16),
        np.array([100, 200, 700, 900, 450, 580], dtype=np.uint16),
    ]
    child = SimpleNamespace(
        stdout=io.BytesIO(b"".join(frame.tobytes() for frame in samples)),
        poll=lambda: 0,
    )
    # FFmpeg's stdout is the boundary: two distinct 10-bit planar frames.
    monkeypatch.setattr("subprocess.Popen", lambda *_args, **_kwargs: child)
    decoder = iter(FrameDecoder(tmp_path / "source.mp4", 2, 2, 2, pix_fmt="yuv420p10le"))
    first, second = next(decoder), next(decoder)
    decoder.close()

    written: list[np.ndarray] = []
    sink = SimpleNamespace(write_frame=lambda frame: written.append(frame.copy()))
    blender = FrameBlender(sink, 2, 2, is_hdr=True)
    blender.emit_crossfade(iter([first, first]), iter([second, second]), 2)
    # The reusable crossfade destination must never overwrite held source bytes.
    np.testing.assert_array_equal(first, samples[0])
    np.testing.assert_array_equal(second, samples[1])
    np.testing.assert_array_equal(written[0], [82, 160, 600, 920, 481, 546])
    np.testing.assert_array_equal(written[1], samples[1])
    assert not first.flags.writeable
    assert not second.flags.writeable
