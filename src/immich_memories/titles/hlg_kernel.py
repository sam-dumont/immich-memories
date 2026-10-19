"""The device kernel behind `hlg_frames.finalize_to_hlg` (#2709).

Kept apart because the kernel library reads its parameter annotations at
compile time, which `from __future__ import annotations` would turn into strings.
"""

from collections.abc import Callable

import numpy as np

from immich_memories.titles.gpu_kernel_backend import ti


def compile_hlg_finalize(
    primaries: np.ndarray,
    luma: tuple[float, float, float],
    sdr_white: float,
    exponent: float,
    oetf: tuple[float, float, float],
) -> Callable[..., None]:
    """Quantize, fade and convert a title frame to HLG in one pass.

    The constants are `hlg_frames`', so the device and the reference it is
    qualified against compute the same thing.
    """
    m = [[float(v) for v in row] for row in primaries]
    luma_r, luma_g, luma_b = luma
    hlg_a, hlg_b, hlg_c = oetf

    @ti.kernel
    def finalize_hlg(
        frame: ti.types.ndarray(dtype=ti.f32, ndim=3),
        output: ti.types.ndarray(ndim=3),
        fade_in_weight: ti.f32,
        fade_in_white: ti.i32,
        fade_out_weight: ti.f32,
        fade_out_white: ti.i32,
        coefficients: ti.types.ndarray(dtype=ti.f32, ndim=1),
    ):
        for y, x in ti.ndrange(frame.shape[0], frame.shape[1]):
            sdr = ti.Vector([0.0, 0.0, 0.0])
            for c in ti.static(range(3)):
                v = ti.max(0.0, ti.min(1.0, frame[y, x, c]))
                # The SDR frame's own quantization and fades, as finalize_output does them.
                value = ti.cast(v * 65535.0 + 0.5, ti.u32)
                value = ti.cast(fade_in_white + value * fade_in_weight, ti.u32)
                value = ti.cast(fade_out_white + value * fade_out_weight, ti.u32)
                sdr[c] = ti.cast(value, ti.f32) / 65535.0
            luma_sdr = 0.299 * sdr[0] + 0.587 * sdr[1] + 0.114 * sdr[2]
            yy = (coefficients[1] + coefficients[0] * luma_sdr - 4096.0) / 56064.0
            cb = (
                coefficients[3] + coefficients[2] * (sdr[2] - luma_sdr) / 1.772 - 32768.0
            ) / 57344.0
            cr = (
                coefficients[5] + coefficients[4] * (sdr[0] - luma_sdr) / 1.402 - 32768.0
            ) / 57344.0
            red = yy + 1.5748 * cr
            blue = yy + 1.8556 * cb
            green = (yy - 0.2126 * red - 0.0722 * blue) / 0.7152
            lr = ti.pow(ti.max(red, 0.0), 2.4)
            lg = ti.pow(ti.max(green, 0.0), 2.4)
            lb = ti.pow(ti.max(blue, 0.0), 2.4)
            display = ti.Vector(
                [
                    (m[0][0] * lr + m[0][1] * lg + m[0][2] * lb) * sdr_white,
                    (m[1][0] * lr + m[1][1] * lg + m[1][2] * lb) * sdr_white,
                    (m[2][0] * lr + m[2][1] * lg + m[2][2] * lb) * sdr_white,
                ]
            )
            luminance = luma_r * display[0] + luma_g * display[1] + luma_b * display[2]
            gain = ti.pow(ti.max(luminance, 1e-12), exponent)
            for c in ti.static(range(3)):
                scene = ti.max(display[c] * gain, 0.0)
                signal = ti.sqrt(3.0 * scene)
                if scene > 1.0 / 12.0:
                    signal = hlg_a * ti.log(ti.max(12.0 * scene - hlg_b, 1e-12)) + hlg_c
                output[y, x, c] = ti.cast(
                    ti.min(65535.0, ti.max(0.0, signal * 65535.0 + 0.5)), ti.u32
                )

    return finalize_hlg
