"""A content-backed title hard-cuts into its clip, so the seam frame IS the clip.

The deblur is the transition: the opening's last frame and the ending's first
are the only frames the viewer compares against the clip on the other side of
the cut. Any look laid over the title there (vignette, grain, bokeh) snaps off
at the cut and reads as the picture jumping.

Run: make test-integration-titles
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import numpy as np
import pytest

os.environ["IMMICH_FORCE_CPU"] = "1"

from immich_memories.titles.content_background import SlowmoBackgroundReader  # noqa: E402
from immich_memories.titles.kernels import KERNELS_AVAILABLE, init_kernels  # noqa: E402
from immich_memories.titles.renderer_kernels import (  # noqa: E402
    KernelTitleConfig,
    KernelTitleRenderer,
)
from tests.integration.conftest import requires_ffmpeg  # noqa: E402

pytestmark = [
    pytest.mark.integration,
    requires_ffmpeg,
    pytest.mark.skipif(not KERNELS_AVAILABLE, reason="no kernel library wheel for this platform"),
]

WIDTH, HEIGHT, FPS, DURATION = 180, 320, 30.0, 2.0
# One 8-bit level of rounding either way through the float pipeline.
SEAM_TOLERANCE = 1.0


@pytest.fixture(scope="module")
def _kernels_on_cpu() -> str:
    backend = init_kernels()
    assert backend is not None
    return backend


@pytest.fixture(scope="module")
def clip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("seam") / "clip.mp4"
    subprocess.run(  # noqa: S603, S607 — fixed argv, no shell
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size={WIDTH}x{HEIGHT}:rate=30:duration=2",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-qp",
            "0",
            str(path),
        ],  # fmt: skip
        check=True,
    )
    return path


def _render(clip: Path, *, reverse: bool) -> tuple[list[np.ndarray], list[np.ndarray]]:
    """The source frames and every rendered frame, as the rendering service configures it."""
    reader = SlowmoBackgroundReader(clip, WIDTH, HEIGHT, FPS, title_duration=DURATION)
    assert reader.is_active
    sources = [frame.astype(np.float64) for frame in reader.source_frames]
    config = KernelTitleConfig(
        width=WIDTH,
        height=HEIGHT,
        fps=FPS,
        duration=DURATION,
        background_reader=reader,
        blur_radius=int(HEIGHT * 0.10),
        gradient_rotation=0.0,
        color_pulse_amount=0.0,
        vignette_pulse=0.0,
        vignette_strength=0.15,
        enable_bokeh=True,
        reverse_blur=reverse,
    )
    renderer = KernelTitleRenderer(config)
    frames = [
        renderer.render_frame(n, "", None).astype(np.float64) for n in range(renderer.total_frames)
    ]
    reader.close()
    return sources, frames


def test_opening_ends_on_the_clip_it_cuts_into(_kernels_on_cpu: str, clip: Path) -> None:
    sources, frames = _render(clip, reverse=False)

    gap = np.abs(frames[-1] - sources[-1])

    assert gap.mean() < SEAM_TOLERANCE, f"last title frame drifts {gap.mean():.2f} from the clip"


def test_ending_starts_on_the_clip_it_cuts_from(_kernels_on_cpu: str, clip: Path) -> None:
    sources, frames = _render(clip, reverse=True)

    gap = np.abs(frames[0] - sources[0])

    assert gap.mean() < SEAM_TOLERANCE, f"first ending frame drifts {gap.mean():.2f} from the clip"
