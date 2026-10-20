"""Title colours keep their RGB through the film's BT.709 tags (#2726).

The title chain used a bare `format=yuv420p` after RGB input, so swscale converted
with its BT.601 default while the stream (and zscale, for HDR) read BT.709: pure
red came back as 255,24,0. These tests push saturated swatches through the real
title filter and encoder and decode them the way a player reads the tags.

Run: make test-integration-titles
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest

from immich_memories.processing.encoding_plan import EncodingPlan, HdrTransfer, OutputCodec
from immich_memories.processing.hdr_utilities import check_zscale_available
from immich_memories.titles.encoding import (
    standalone_title_encoding_plan,
    title_color_filter,
    title_encoder_args,
)
from tests.integration.conftest import requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]

# Saturated colours are where the BT.601/BT.709 matrices disagree most.
SWATCHES = [(255, 0, 0), (0, 160, 80), (200, 40, 120), (30, 60, 220), (0, 255, 255)]
BLOCK = 64
HEIGHT = 32
TOLERANCE = 2
WIDTH = BLOCK * len(SWATCHES)


def _picture(dtype: type) -> np.ndarray:
    scale = 257 if dtype == np.uint16 else 1
    picture = np.zeros((HEIGHT, WIDTH, 3), dtype)
    for index, colour in enumerate(SWATCHES):
        picture[:, index * BLOCK : (index + 1) * BLOCK] = np.array(colour) * scale
    return picture


def _hdr_plan(transfer: HdrTransfer) -> EncodingPlan:
    return EncodingPlan(
        codec=OutputCodec.H265,
        encoder="libx265",
        encoder_args=(),
        target_transfer=transfer,
        tone_map_to_sdr=False,
        pixel_format="yuv420p10le",
        container="mp4",
    )


def _run(args: list[str], data: bytes | None = None) -> bytes:
    result = subprocess.run(  # noqa: S603
        ["ffmpeg", "-v", "error", *args], input=data, capture_output=True, timeout=120, check=True
    )
    return result.stdout


def _decode_bt709_tv(raw: bytes) -> np.ndarray:
    """Centre pixel of each swatch from raw yuv420p, read as BT.709 limited range."""
    luma = np.frombuffer(raw, np.uint8, WIDTH * HEIGHT).reshape(HEIGHT, WIDTH).astype(float)
    chroma_size = (WIDTH // 2) * (HEIGHT // 2)
    offset = WIDTH * HEIGHT
    blue = np.frombuffer(raw, np.uint8, chroma_size, offset).reshape(HEIGHT // 2, -1)
    red = np.frombuffer(raw, np.uint8, chroma_size, offset + chroma_size).reshape(HEIGHT // 2, -1)
    decoded = []
    for index in range(len(SWATCHES)):
        x = index * BLOCK + BLOCK // 2
        y_norm = (luma[HEIGHT // 2, x] - 16.0) / 219.0
        cb = (float(blue[HEIGHT // 4, x // 2]) - 128.0) / 224.0
        cr = (float(red[HEIGHT // 4, x // 2]) - 128.0) / 224.0
        r = y_norm + 1.5748 * cr
        b = y_norm + 1.8556 * cb
        g = (y_norm - 0.2126 * r - 0.0722 * b) / 0.7152
        decoded.append(np.clip(np.rint(np.array([r, g, b]) * 255.0), 0, 255))
    return np.array(decoded)


def test_sdr_title_swatches_decode_to_their_rgb(tmp_path: Path) -> None:
    plan = standalone_title_encoding_plan()
    video = tmp_path / "swatches.mp4"
    _run(
        [
            "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{WIDTH}x{HEIGHT}", "-r", "10",
            "-i", "pipe:0", "-vf", title_color_filter(plan), *title_encoder_args(plan),
            "-frames:v", "2", str(video),
        ],
        _picture(np.uint8).tobytes() * 2,
    )  # fmt: skip
    raw = _run(
        ["-i", str(video), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "yuv420p", "pipe:1"]
    )

    decoded = _decode_bt709_tv(raw)

    worst = np.abs(decoded - np.array(SWATCHES)).max()
    assert worst <= TOLERANCE, f"decoded {decoded.tolist()} vs {SWATCHES}"


def _bt709_tv_planes(picture16: np.ndarray) -> bytes:
    """The swatches as 16-bit 4:4:4 BT.709 limited-range Y'CbCr, computed independently."""
    rgb = picture16.astype(np.float64) / 65535.0
    y = rgb @ np.array((0.2126, 0.7152, 0.0722))
    cb = (rgb[..., 2] - y) / 1.8556
    cr = (rgb[..., 0] - y) / 1.5748
    planes = [4096 + 56064 * y, 32768 + 57344 * cb, 32768 + 57344 * cr]
    return b"".join(np.rint(p).astype("<u2").tobytes() for p in planes)


@pytest.mark.parametrize("transfer", [HdrTransfer.PQ, HdrTransfer.HLG])
def test_hdr_title_swatches_match_correct_bt709_input(transfer: HdrTransfer) -> None:
    if not check_zscale_available():
        pytest.skip("FFmpeg has no zscale filter")
    plan = _hdr_plan(transfer)
    size = ["-s", f"{WIDTH}x{HEIGHT}", "-f", "rawvideo"]
    out = ["-f", "rawvideo", "-pix_fmt", plan.pixel_format, "pipe:1"]
    picture = _picture(np.uint16)

    actual = _run(
        [*size, "-pix_fmt", "rgb48le", "-i", "pipe:0", "-vf", title_color_filter(plan), *out],
        picture.tobytes(),
    )
    # The same transfer chain fed Y'CbCr that really is BT.709, as the tags say.
    expected = _run(
        [
            *size, "-pix_fmt", "yuv444p16le", "-i", "pipe:0", "-vf",
            title_color_filter(plan, rgb_input=False), *out,
        ],
        _bt709_tv_planes(picture),
    )  # fmt: skip

    difference = np.abs(
        np.frombuffer(actual, "<u2").astype(np.int64) - np.frombuffer(expected, "<u2")
    )
    assert difference.max() <= TOLERANCE, f"{transfer.value}: off by {difference.max()} codes"


def test_sdr_title_background_prerender_keeps_the_clip_colours(tmp_path: Path) -> None:
    from immich_memories.processing.assembly_config import (
        AssemblyClip,
        AssemblySettings,
        standalone_assembly_encoding_plan,
    )
    from immich_memories.processing.ffmpeg_prober import FFmpegProber
    from immich_memories.processing.title_background_renderer import TitleBackgroundRenderer

    source = tmp_path / "swatches.mkv"
    # A correctly tagged BT.709 clip: what the film's own clips look like.
    _run(
        [
            "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{WIDTH}x{HEIGHT}", "-r", "4",
            "-i", "pipe:0", "-vf",
            "scale=in_range=full:out_color_matrix=bt709:out_range=tv,format=yuv420p,"
            "setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv",
            "-c:v", "ffv1", "-frames:v", "8", str(source),
        ],
        _picture(np.uint8).tobytes() * 8,
    )  # fmt: skip
    settings = AssemblySettings(encoding_plan=standalone_assembly_encoding_plan())
    renderer = TitleBackgroundRenderer(settings, FFmpegProber(settings))

    output = renderer.render_first_clip([AssemblyClip(source, 2)], tmp_path, WIDTH, HEIGHT, 4, None)

    assert output is not None
    raw = _run(
        ["-i", str(output), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "yuv420p", "pipe:1"]
    )
    decoded = _decode_bt709_tv(raw)
    worst = np.abs(decoded - np.array(SWATCHES)).max()
    assert worst <= TOLERANCE, f"decoded {decoded.tolist()} vs {SWATCHES}"
