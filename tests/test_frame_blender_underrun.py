"""A clip that runs out early keeps its planned length in the film (#2785).

On the render worker a 150-clip film came back 445 frames short of its preview
with nothing in the log. The blender holds the last frame written for every
missing one, and says so, so the film, its music and its captions stay aligned.
"""

from __future__ import annotations

import logging

import numpy as np

from immich_memories.processing.streaming_frame_blender import FrameBlender


class _Sink:
    def __init__(self) -> None:
        self.frames: list[np.ndarray] = []

    def write_frame(self, frame: np.ndarray) -> None:
        self.frames.append(frame.copy())


def _frames(values: list[int]):
    for value in values:
        yield np.full((4, 6, 3), value, dtype=np.uint8)


def _blender(sink: _Sink, total: int = 100) -> FrameBlender:
    return FrameBlender(sink, 6, 4, total_frames=total)


def test_a_short_clip_is_held_on_its_last_frame_for_its_planned_length(caplog):
    sink = _Sink()
    blender = _blender(sink)

    with caplog.at_level(logging.WARNING):
        blender.emit_body(_frames([10, 20, 30]), 7, clip="clip 3 (still.mp4)")

    assert [int(frame[0, 0, 0]) for frame in sink.frames] == [10, 20, 30, 30, 30, 30, 30]
    assert blender.frames_written == 7
    assert "Frame underrun in clip 3 (still.mp4)" in caplog.text
    assert "missing 4" in caplog.text


def test_a_clip_with_no_frames_left_holds_the_frame_before_it():
    sink = _Sink()
    blender = _blender(sink)
    blender.emit_body(_frames([10, 20]), 2)

    blender.emit_body(_frames([]), 3)

    assert [int(frame[0, 0, 0]) for frame in sink.frames] == [10, 20, 20, 20, 20]


def test_a_fade_whose_clips_both_run_out_still_writes_every_frame():
    sink = _Sink()
    blender = _blender(sink)

    blender.emit_crossfade(_frames([100, 100]), _frames([200]), 6)

    assert len(sink.frames) == blender.frames_written == 6
    # The ends of both clips are held and the blend keeps moving towards the next one.
    assert [int(frame[0, 0, 0]) for frame in sink.frames] == [117, 133, 150, 167, 183, 200]


def test_a_full_clip_writes_exactly_its_frames(caplog):
    sink = _Sink()
    blender = _blender(sink)

    with caplog.at_level(logging.WARNING):
        blender.emit_body(_frames([1, 2, 3, 4]), 3)

    assert [int(frame[0, 0, 0]) for frame in sink.frames] == [1, 2, 3]
    assert "underrun" not in caplog.text
