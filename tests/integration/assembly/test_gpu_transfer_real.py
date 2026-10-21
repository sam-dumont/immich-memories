"""The GPU transfer conversion gives zscale's picture, within a code value.

Runs where this machine's FFmpeg runs libplacebo on a GPU and passes the
transfer probe, and skips elsewhere. Each clip goes through the real decoder
twice, once with zscale and once with the libplacebo shader, and the frames are
compared in 10-bit code values: the Dolby Vision 8.4 phone clip (HLG, stored
sideways) tone-mapped to SDR and converted to PQ, a small SDR clip converted to
HLG, and a 4:3 SDR clip given a blurred background in a portrait PQ film.

That last one decoded to no frame at all on FFmpeg 6.1 with libplacebo v6.338
while FFmpeg exited 0 (#2792), so it is also decoded whole and counted.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from immich_memories.processing import gpu_transfer, streaming_frame_decoder
from immich_memories.processing.hdr_utilities import (
    detect_color_primaries,
    detect_hdr_type,
    get_colorspace_filter,
)
from immich_memories.processing.probe_cache import ProbeCache
from tests.integration.conftest import requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]

PHONE_CLIP = Path(__file__).parents[2] / "fixtures" / "hdr_samples" / "dolby_vision_84.mov"
FRAMES = 12
# Captured before the suite pins the probe's answer for every other test.
REAL_PROBE = gpu_transfer.gpu_transfer_works


@pytest.fixture(scope="module")
def gpu_conversions():
    if not REAL_PROBE():
        pytest.skip("FFmpeg here does not run libplacebo on a GPU within a code value of zscale")


def _sdr_clip(path: Path, size: str = "640x360") -> Path:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", f"testsrc2=size={size}:rate=30:duration=1,noise=alls=6:allf=t",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-color_primaries", "bt709",
         "-color_trc", "bt709", "-colorspace", "bt709", str(path)],
        check=True, capture_output=True,
    )  # fmt: skip
    return path


def _frames(
    path: Path, target: str, canvas, monkeypatch, *, gpu: bool, limit: int | None = FRAMES
) -> list[np.ndarray]:
    cache = ProbeCache()
    ctx = SimpleNamespace(
        hdr_type=target,
        pix_fmt="yuv420p" if target == "sdr" else "yuv420p10le",
        clip_hdr_types=[detect_hdr_type(path, probe_cache=cache)],
        clip_primaries=[detect_color_primaries(path, probe_cache=cache)],
        colorspace_filter=get_colorspace_filter(target),
    )
    # WHY: the switch under comparison; zscale is what every film got before.
    monkeypatch.setattr(gpu_transfer, "gpu_transfer_works", REAL_PROBE if gpu else lambda: False)
    clip = SimpleNamespace(path=path, duration=1.0, is_title_screen=False)
    decoder = streaming_frame_decoder.make_decoder(
        clip, 0, *canvas, 30, ctx, scale_mode="blur",
        hdr_type=None if target == "sdr" else target, probe_cache=cache, planar_sdr=True,
        # Planar: zscale's two-step HLG-to-PQ chain writes P010 two codes brighter than
        # its own maths, so the planar pipe is the reference both are measured against.
        hdr_pipe_format="yuv420p10le",
    )  # fmt: skip
    assert ("libplacebo" in decoder._build_vf()) is gpu
    frames = []
    for frame in decoder:
        values = frame.astype(np.float32)
        frames.append(values if target != "sdr" else values * 4)
        if len(frames) == limit:
            break
    return frames


@pytest.mark.parametrize(
    ("source", "target", "canvas"),
    [
        ("phone", "sdr", (1080, 1920)),
        ("phone", "pq", (1080, 1920)),
        ("small_sdr", "hlg", (640, 360)),
        ("four_three_sdr", "pq", (1080, 1920)),
    ],
)
def _source(name: str, tmp_path: Path) -> Path:
    if name == "phone":
        return PHONE_CLIP
    size = "640x480" if name == "four_three_sdr" else "640x360"
    return _sdr_clip(tmp_path / f"{name}.mp4", size)


def test_the_gpu_conversion_matches_zscale(
    tmp_path, gpu_conversions, monkeypatch, source, target, canvas
):
    path = _source(source, tmp_path)

    cpu = _frames(path, target, canvas, monkeypatch, gpu=False)
    gpu = _frames(path, target, canvas, monkeypatch, gpu=True)

    assert len(cpu) == len(gpu) == FRAMES
    luma = canvas[0] * canvas[1]
    for before, after in zip(cpu, gpu, strict=True):
        assert abs(before[:luma].mean() - after[:luma].mean()) < 1
        assert np.abs(before[:luma] - after[:luma]).mean() < 2
        assert np.abs(before[luma:] - after[luma:]).mean() < 2


def test_a_blur_filled_clip_converted_on_the_gpu_keeps_every_frame(
    tmp_path, gpu_conversions, monkeypatch
):
    """#2792: the blur fill followed by libplacebo gave no frame, with FFmpeg exiting 0."""
    path = _sdr_clip(tmp_path / "four_three.mp4", "640x480")

    frames = _frames(path, "pq", (1080, 1920), monkeypatch, gpu=True, limit=None)

    assert len(frames) == 30
