"""Which clips the assembly decodes on the hardware (#2709).

Only the 4:2:0 H.264 and HEVC formats whose hardware frames a format filter
repacks into exactly the software decoder's; anything else stays in software.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from immich_memories.processing import gpu_frame_graph
from immich_memories.processing.gpu_frame_graph import hardware_decode_for
from immich_memories.processing.hardware import HWAccelBackend, HWAccelCapabilities
from immich_memories.processing.streaming_frame_decoder import FrameDecoder

APPLE = HWAccelCapabilities(
    backend=HWAccelBackend.APPLE, supports_h264_decode=True, supports_h265_decode=True
)


class _Probes:
    """The probe boundary: what ffprobe says about the clip."""

    def __init__(self, codec: str, pixel_format: str | None) -> None:
        self._probe = SimpleNamespace(codec=codec, pixel_format=pixel_format)

    def get(self, _path):
        return self._probe


@pytest.fixture(autouse=True)
def trusted_decoder(monkeypatch):
    # WHY: replaces the FFmpeg runs that compare the hardware decode with the software one.
    monkeypatch.setattr(gpu_frame_graph, "hardware_decode_matches", lambda *_args: True)


@pytest.mark.parametrize(
    ("codec", "pixel_format", "decoded"),
    [
        ("hevc", "yuv420p10le", True),
        ("h264", "yuv420p", True),
        ("hevc", "yuv422p10le", False),
        ("vp9", "yuv420p", False),
        ("h264", None, False),
    ],
)
def test_only_formats_repacked_exactly_go_to_the_hardware(codec, pixel_format, decoded):
    gate = hardware_decode_for(Path("clip.mov"), APPLE, _Probes(codec, pixel_format))

    assert (gate is not None) is decoded
    if decoded:
        assert gate == (("-hwaccel", "videotoolbox"), pixel_format)


def test_a_decoder_that_strays_from_the_software_picture_decodes_in_software(monkeypatch):
    seen = []
    # WHY: replaces the FFmpeg runs; this decoder's frames differ from the software ones.
    monkeypatch.setattr(
        gpu_frame_graph, "hardware_decode_matches", lambda *args: seen.append(args) and False
    )

    assert hardware_decode_for(Path("clip.mov"), APPLE, _Probes("h264", "yuv420p")) is None
    assert seen == [(("-hwaccel", "videotoolbox"), "h264", "yuv420p")]


def test_no_capabilities_decode_in_software():
    assert hardware_decode_for(Path("clip.mov"), None, _Probes("hevc", "yuv420p10le")) is None


def test_the_hardware_frames_are_repacked_before_any_other_filter():
    decoder = FrameDecoder(
        Path("clip.mov"), 64, 64, 30, rotation=90,
        hardware_decode=(("-hwaccel", "videotoolbox"), "yuv420p10le"),
    )  # fmt: skip

    assert decoder._build_vf().startswith("format=yuv420p10le,transpose=1,")
