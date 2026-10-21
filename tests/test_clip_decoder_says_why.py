"""A clip that comes out short says why, in the film's log (#2792).

On the render worker four blur-fill clips decoded to no frames at all. FFmpeg
exited 0 and its stderr went nowhere, so the log only said a frame was held.
The underrun warning now carries what FFmpeg said about the clip, and a fade
that runs out on either side says which.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import numpy as np

from immich_memories.processing.streaming_frame_blender import FrameBlender
from immich_memories.processing.streaming_frame_decoder import FrameDecoder


class _Sink:
    def __init__(self) -> None:
        self.frames: list[np.ndarray] = []

    def write_frame(self, frame: np.ndarray) -> None:
        self.frames.append(frame.copy())


def _one_second_clip(path: Path) -> Path:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "testsrc2=size=64x48:rate=30:duration=1",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
        check=True, capture_output=True,
    )  # fmt: skip
    return path


def _frames(values: list[int]):
    for value in values:
        yield np.full(64 * 48 * 3 // 2, value, dtype=np.uint8)


def test_a_clip_that_decodes_to_nothing_logs_what_ffmpeg_said(tmp_path, caplog):
    clip = _one_second_clip(tmp_path / "clip.mp4")
    # A head trimmed past the clip's end: FFmpeg exits 0 having written no frame.
    decoder = FrameDecoder(clip, 64, 48, 30, pix_fmt="yuv420p", from_seconds=5.0)
    sink = _Sink()
    blender = FrameBlender(sink, 64, 48, planar_sdr=True, total_frames=20)
    blender.emit_body(_frames([7]), 1)

    with caplog.at_level(logging.WARNING):
        blender.emit_body(decoder.iter_borrowed_frames(), 10, clip="clip 1 (clip.mp4)")

    assert len(sink.frames) == 11
    underrun = next(r.getMessage() for r in caplog.records if "underrun" in r.getMessage())
    assert "Output file is empty" in underrun


def test_a_clip_that_decodes_fully_logs_nothing(tmp_path, caplog):
    clip = _one_second_clip(tmp_path / "clip.mp4")
    decoder = FrameDecoder(clip, 64, 48, 30, pix_fmt="yuv420p")
    blender = FrameBlender(_Sink(), 64, 48, planar_sdr=True, total_frames=30)

    with caplog.at_level(logging.WARNING):
        blender.emit_body(decoder.iter_borrowed_frames(), 30)

    assert caplog.text == ""


def test_a_fade_into_a_clip_with_no_frames_says_so(caplog):
    blender = FrameBlender(_Sink(), 64, 48, planar_sdr=True, total_frames=20)

    with caplog.at_level(logging.WARNING):
        blender.emit_crossfade(_frames([100, 100, 100]), _frames([]), 3)

    messages = [r.getMessage() for r in caplog.records]
    assert len(messages) == 1
    assert "incoming clip" in messages[0]
    assert "3 of 3" in messages[0]
