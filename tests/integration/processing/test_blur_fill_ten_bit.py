"""A letterboxed HDR clip keeps its 10-bit levels through the blur fill (#1527).

The fill's overlay used to run in its default 8-bit format, so every luma code
of an HLG film came out a multiple of 4 wherever a clip did not fill the canvas.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from immich_memories.processing.streaming_frame_decoder import make_decoder
from tests.integration.conftest import requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]

SOURCE_W, SOURCE_H = 640, 360
CANVAS_W, CANVAS_H = 360, 640


def _hlg_ramp(path: Path) -> None:
    """A landscape 10-bit HLG clip whose luma climbs one code a column, stored losslessly."""
    luma = np.broadcast_to(
        np.linspace(64, 940, SOURCE_W).round().astype(np.uint16), (SOURCE_H, SOURCE_W)
    )
    chroma = np.full((SOURCE_H // 2, SOURCE_W // 2), 512, dtype=np.uint16)
    frame = np.concatenate([luma.ravel(), chroma.ravel(), chroma.ravel()]).astype("<u2")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "yuv420p10le"]
        + ["-s", f"{SOURCE_W}x{SOURCE_H}", "-r", "30", "-i", "-", "-frames:v", "10"]
        + ["-c:v", "ffv1", "-color_range", "tv", "-color_primaries", "bt2020"]
        + ["-color_trc", "arib-std-b67", "-colorspace", "bt2020nc", str(path)],
        input=frame.tobytes() * 10,
        check=True,
    )


def test_a_letterboxed_hlg_clip_keeps_ten_bit_luma(tmp_path):
    source = tmp_path / "ramp.mkv"
    _hlg_ramp(source)
    clip = SimpleNamespace(
        path=source, is_title_screen=False, rotation_override=None, input_seek=0.0
    )
    decoder = make_decoder(clip, 0, CANVAS_W, CANVAS_H, 30, None, False, None, None, "blur", "hlg")
    frame = next(iter(decoder))

    luma = frame[: CANVAS_W * CANVAS_H].reshape(CANVAS_H, CANVAS_W)
    row = luma[CANVAS_H // 2]
    assert not np.all(row % 4 == 0)
    # 360 output columns over 876 source codes: an 8-bit path holds at most 220.
    assert len(np.unique(row)) >= 300
