"""A hardware decoder is trusted only when it gives the software decoder's frames (#2790)."""

from __future__ import annotations

import shutil

import pytest

from immich_memories.processing.hardware_decode_check import hardware_decode_matches

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def test_a_decoder_that_gives_the_software_frames_is_trusted():
    assert hardware_decode_matches((), "h264", "yuv420p")


def test_a_decoder_that_changes_the_picture_is_not():
    # Skipping the deblocking filter changes the H.264 picture, as a decoder that
    # gets the chroma wrong (VideoToolbox on a virtual Mac) does.
    assert not hardware_decode_matches(("-skip_loop_filter", "all"), "h264", "yuv420p")


def test_a_decoder_that_cannot_run_is_not():
    assert not hardware_decode_matches(("-hwaccel", "no-such-hwaccel"), "h264", "yuv420p")


def test_a_codec_without_a_known_clip_is_not():
    assert not hardware_decode_matches((), "vp9", "yuv420p")
