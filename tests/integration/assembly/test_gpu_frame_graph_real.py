"""The GPU filter graph gives the CPU chain's picture, within a few code values.

Runs where this machine's FFmpeg passes the GPU filter probe (CUDA or
VideoToolbox) and skips elsewhere. Each clip is decoded twice through the real
decoder, once on each path, and compared frame by frame in 10-bit code values:
the Dolby Vision 8.4 phone clip (HLG, stored sideways) with a blur fill, kept HLG
and tone-mapped to SDR, and a small SDR clip converted to HLG and enlarged.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from immich_memories.processing import gpu_frame_graph, streaming_frame_decoder
from immich_memories.processing.hardware import (
    detect_hardware_acceleration,
    get_ffmpeg_hwaccel_args,
)
from immich_memories.processing.hardware_decode_check import hardware_decode_matches
from immich_memories.processing.hdr_utilities import (
    detect_color_primaries,
    detect_hdr_type,
    get_colorspace_filter,
)
from immich_memories.processing.probe_cache import ProbeCache
from tests.integration.conftest import requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]

PHONE_CLIP = Path(__file__).parents[2] / "fixtures" / "hdr_samples" / "dolby_vision_84.mov"
FRAMES = 20


@pytest.fixture(scope="module")
def capabilities():
    found = detect_hardware_acceleration()
    backend = gpu_frame_graph.gpu_backend(found)
    if backend is None or not gpu_frame_graph.gpu_filters_work(backend):
        pytest.skip("no GPU filter graph on this machine")
    return found


def _sdr_clip(path: Path) -> Path:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "testsrc2=size=640x360:rate=30:duration=1,noise=alls=6:allf=t",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
        check=True, capture_output=True,
    )  # fmt: skip
    return path


def _frames(path: Path, capabilities, target: str, canvas, monkeypatch, *, gpu: bool):
    cache = ProbeCache()
    ctx = SimpleNamespace(
        hdr_type=target,
        pix_fmt="yuv420p" if target == "sdr" else "yuv420p10le",
        clip_hdr_types=[detect_hdr_type(path, probe_cache=cache)],
        clip_primaries=[detect_color_primaries(path, probe_cache=cache)],
        colorspace_filter=get_colorspace_filter(target),
        decode_capabilities=capabilities,
    )
    if not gpu:
        # WHY: the switch under comparison; the CPU chain is what every film got before.
        monkeypatch.setattr(streaming_frame_decoder, "gpu_frame_graph_for_path", lambda *_: None)
    clip = SimpleNamespace(path=path, duration=1.0, is_title_screen=False)
    decoder = streaming_frame_decoder.make_decoder(
        clip, 0, *canvas, 30, ctx, scale_mode="blur",
        hdr_type=None if target == "sdr" else target, probe_cache=cache, planar_sdr=True,
        hdr_pipe_format="p010le",
    )  # fmt: skip
    assert ("hwdownload" in decoder._build_vf()) is gpu
    frames = []
    for frame in decoder:
        values = frame.astype(np.float32)
        frames.append(values / 64 if target != "sdr" else values * 4)
        if len(frames) == FRAMES:
            break
    monkeypatch.undo()
    return frames


def _decoder_trusted(path: Path, capabilities) -> bool:
    probe = ProbeCache().get(path)
    codec = {"h264": "h264", "hevc": "h265"}[probe.codec]
    args = get_ffmpeg_hwaccel_args(
        capabilities, operation="decode", codec=codec, for_software_filters=True
    )
    return hardware_decode_matches(tuple(args), codec, str(probe.pixel_format))


@pytest.mark.parametrize(
    ("source", "target", "canvas"),
    [
        ("phone", "hlg", (1920, 1080)),
        ("phone", "sdr", (1920, 1080)),
        ("small_sdr", "hlg", (1280, 720)),
    ],
)
def test_the_gpu_graph_matches_the_cpu_chain(
    tmp_path, capabilities, monkeypatch, source, target, canvas
):
    path = PHONE_CLIP if source == "phone" else _sdr_clip(tmp_path / "small.mp4")
    if gpu_frame_graph.gpu_frame_graph_for_path(path, capabilities, ProbeCache()) is None:
        # The graph is refused only where this machine's decoder strays from the
        # software picture for the clip's codec (VideoToolbox's H.264 on a virtual Mac).
        assert not _decoder_trusted(path, capabilities)
        return

    cpu = _frames(path, capabilities, target, canvas, monkeypatch, gpu=False)
    gpu = _frames(path, capabilities, target, canvas, monkeypatch, gpu=True)

    assert len(cpu) == len(gpu) == FRAMES
    luma = canvas[0] * canvas[1]
    for before, after in zip(cpu, gpu, strict=True):
        assert abs(before[:luma].mean() - after[:luma].mean()) < 2
        assert np.abs(before[:luma] - after[:luma]).mean() < 5
        assert np.abs(before[luma:] - after[luma:]).mean() < 4
