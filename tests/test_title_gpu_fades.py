"""GPU fades retain the integer-frame fade contract in SDR and HDR."""

import numpy as np
import pytest

from immich_memories.titles.kernels import init_kernels
from immich_memories.titles.renderer_kernels import KernelTitleConfig, KernelTitleRenderer


@pytest.mark.parametrize("color", ["white", "black"])
@pytest.mark.parametrize("hdr", [False, True])
@pytest.mark.parametrize("duration", [0.5, 2.0])
@pytest.mark.parametrize("fade_in,fade_out", [(True, False), (False, True), (True, True)])
def test_gpu_fade_matches_quantized_cpu_reference(color, hdr, duration, fade_in, fade_out):
    if not init_kernels():
        pytest.skip("no working kernel backend")
    cfg = KernelTitleConfig(
        width=32,
        height=24,
        fps=10,
        duration=duration,
        hdr=hdr,
        enable_bokeh=False,
        enable_noise=False,
        blur_radius=0,
    )
    renderer = KernelTitleRenderer(cfg)
    edge = 0 if color == "black" else (65535 if hdr else 255)
    for number in range(renderer.total_frames):
        expected = renderer.render_frame(number, "", None)
        if fade_in and number < 8:
            alpha = 1.0 - (1.0 - number / 8) ** 2
            expected = (int(edge * (1 - alpha)) + expected * alpha).astype(expected.dtype)
        start = renderer.total_frames - 15
        if fade_out and number >= start:
            alpha = ((number - start) / 15) ** 2
            expected = (int(edge * alpha) + expected * (1 - alpha)).astype(expected.dtype)
        actual = renderer.render_frame(
            number, "", None, fade_from_white=fade_in, fade_to_white=fade_out, fade_color=color
        )
        # One native code value permits Metal f32 vs NumPy f64 rounding.
        np.testing.assert_allclose(actual, expected, atol=1, rtol=0)
