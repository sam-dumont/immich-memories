"""An HLG title leaves the renderer in HLG, within a code of the zscale chain (#2709).

An HLG film converted every title, card and divider frame from SDR with zscale,
about 80 ms of CPU a frame at 1080x1920. The renderer now applies the same
conversion on the device as it quantizes the frame. These tests render the same
card both ways, losslessly, and compare what the film would decode, and they
count the transfer conversions FFmpeg is still asked for.

Run: make test-integration-titles
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import numpy as np
import pytest

os.environ["IMMICH_FORCE_CPU"] = "1"

from immich_memories.processing.encoding_plan import (  # noqa: E402
    EncodingPlan,
    HdrTransfer,
    OutputCodec,
    intermediate_encoding_plan,
)
from immich_memories.titles import hlg_frames, kernel_video  # noqa: E402
from immich_memories.titles.kernels import KERNELS_AVAILABLE, init_kernels  # noqa: E402
from immich_memories.titles.renderer_kernels import KernelTitleConfig  # noqa: E402
from tests.integration.conftest import requires_ffmpeg  # noqa: E402

pytestmark = [pytest.mark.integration, requires_ffmpeg]

WIDTH, HEIGHT = 320, 180


@pytest.fixture(scope="module")
def _kernels_on_cpu():
    if not KERNELS_AVAILABLE:
        pytest.skip("no kernel library wheel for this platform")
    assert init_kernels() is not None


def _hlg_plan(pixel_format: str = "yuv420p10le") -> EncodingPlan:
    film = EncodingPlan(
        codec=OutputCodec.H265,
        encoder="libx265",
        encoder_args=(),
        target_transfer=HdrTransfer.HLG,
        tone_map_to_sdr=False,
        pixel_format=pixel_format,
        container="mp4",
    )
    # Lossless, so the comparison sees the conversion and not two encoders' noise.
    return intermediate_encoding_plan(film, lossless=True)


def _card(path: Path, monkeypatch, *, on_device: bool) -> list[str]:
    commands: list[str] = []
    real_popen = subprocess.Popen

    def recording_popen(cmd, *args, **kwargs):
        if str(cmd[-1]) == str(path):
            commands.append(" ".join(map(str, cmd)))
        return real_popen(cmd, *args, **kwargs)

    # WHY: a spy on the FFmpeg boundary, to read the card's own encode command.
    monkeypatch.setattr(kernel_video.subprocess, "Popen", recording_popen)
    if not on_device:
        # WHY: the reference is the chain every earlier release ran.
        monkeypatch.setattr(kernel_video, "title_frames_in_hlg", lambda _plan: None)
    config = KernelTitleConfig(width=WIDTH, height=HEIGHT, fps=10.0, duration=2.0)
    kernel_video.create_title_video_gpu(
        "A card title",
        "Its subtitle",
        path,
        config=config,
        fade_from_white=True,
        encoding_plan=_hlg_plan(),
    )
    return commands


def _decoded(path: Path) -> np.ndarray:
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-f",
            "rawvideo",
            "-pix_fmt",
            "yuv420p10le",
            "-",
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    return np.frombuffer(result.stdout, dtype=np.uint16).astype(np.int64)


def test_an_hlg_card_rendered_on_the_device_matches_the_zscale_chain(
    _kernels_on_cpu, tmp_path, monkeypatch
):
    reference = tmp_path / "zscale.mp4"
    device = tmp_path / "device.mp4"
    with monkeypatch.context() as patched:
        old_commands = _card(reference, patched, on_device=False)
    new_commands = _card(device, monkeypatch, on_device=True)

    expected, actual = _decoded(reference), _decoded(device)
    assert expected.size == actual.size > 0
    assert np.abs(actual - expected).max() <= 1
    # The transfer conversion ran in FFmpeg on every frame before, and not at all now.
    assert len(old_commands) == len(new_commands) == 1
    assert "tin=bt709:t=arib-std-b67" in old_commands[0]
    assert "tin=bt709" not in new_commands[0]


@pytest.mark.parametrize("pixel_format", ["yuv420p10le", "p010le"])
def test_this_ffmpeg_qualifies_the_device_conversion(pixel_format):
    """The probe compares against the real chain; a mismatch would keep zscale."""
    film = EncodingPlan(
        codec=OutputCodec.H265,
        encoder="hevc_videotoolbox",
        encoder_args=(),
        target_transfer=HdrTransfer.HLG,
        tone_map_to_sdr=False,
        pixel_format=pixel_format,
        container="mp4",
    )
    assert hlg_frames.title_frames_in_hlg(film) is not None


def test_a_pq_film_keeps_ffmpegs_conversion():
    """zscale may approximate the PQ curve on some machines, so PQ never qualifies."""
    film = EncodingPlan(
        codec=OutputCodec.H265,
        encoder="libx265",
        encoder_args=(),
        target_transfer=HdrTransfer.PQ,
        tone_map_to_sdr=False,
        pixel_format="yuv420p10le",
        container="mp4",
    )
    assert hlg_frames.title_frames_in_hlg(film) is None
