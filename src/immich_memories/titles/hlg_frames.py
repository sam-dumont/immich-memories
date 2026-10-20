"""Title frames rendered straight into an HLG film's transfer (#2709).

A title, card or divider is drawn in SDR, and an HLG film used to convert every
frame with zscale: about 80 ms of CPU a frame at 1080x1920, nearly all of it the
transfer functions. The renderer now applies the same conversion as it quantizes
each frame, and FFmpeg keeps only zscale's matrix and chroma steps.

The conversion reproduces what the FFmpeg chain did, including how its first
step reads the SDR pixels (`title_color_filter`): swscale turns RGB into BT.709
limited-range Y'CbCr, which zscale then reads as BT.709 and converts with
the BT.1886 curve, at 203 nits in a 1000-nit HLG signal. swscale's scale and
offset are measured on the FFmpeg that is installed, and the whole conversion has to
land within one code of that chain on a reference picture before it is used:
pixels qualify it, not a version number.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache

import numpy as np

from immich_memories.processing.encoding_plan import EncodingPlan, HdrTransfer, OutputCodec
from immich_memories.processing.hdr_utilities import RGB_TO_BT709_TV

logger = logging.getLogger(__name__)

# BT.709 to BT.2020 primaries in linear light (ITU-R BT.2087).
_BT709_TO_BT2020 = np.array(
    [
        [0.627403895934699, 0.329283038377884, 0.043313065687417],
        [0.069097289358232, 0.919540395075459, 0.011362315566309],
        [0.016391438875150, 0.088013307877226, 0.895595253247624],
    ]
)
_BT2020_LUMA = (0.2627, 0.6780, 0.0593)
# SDR reference white in a 1000-nit HLG display signal, and that display's system gamma.
_SDR_IN_HLG = 203.0 / 1000.0
_HLG_GAMMA = 1.2
_HLG_A = 0.17883277
_HLG_B = 1.0 - 4.0 * _HLG_A
_HLG_C = 0.5 - _HLG_A * float(np.log(4.0 * _HLG_A))
# The formats zscale writes itself; the title chain reached any other from 4:4:4.
_ZSCALE_WRITES = frozenset({"yuv420p10le", "yuv422p10le"})
# Larger than any rounding the chains disagree on, smaller than anything visible.
_MAX_CODE_DIFFERENCE = 1


@dataclass(frozen=True)
class SdrToHlg:
    """How swscale maps full-range RGB to 16-bit limited Y'CbCr: scale and offset per plane."""

    luma_scale: float
    luma_offset: float
    blue_scale: float
    blue_offset: float
    red_scale: float
    red_offset: float


def sdr_to_hlg(rgb16: np.ndarray, conversion: SdrToHlg) -> np.ndarray:
    """SDR 16-bit RGB to HLG 16-bit RGB in BT.2020, as the title chain converted it."""
    rgb = rgb16.astype(np.float64) / 65535.0
    luma = rgb @ np.array((0.2126, 0.7152, 0.0722))
    y = (conversion.luma_offset + conversion.luma_scale * luma - 4096.0) / 56064.0
    cb = conversion.blue_offset + conversion.blue_scale * (rgb[..., 2] - luma) / 1.8556 - 32768.0
    cr = conversion.red_offset + conversion.red_scale * (rgb[..., 0] - luma) / 1.5748 - 32768.0
    cb, cr = cb / 57344.0, cr / 57344.0
    red = y + 1.5748 * cr
    blue = y + 1.8556 * cb
    green = (y - 0.2126 * red - 0.0722 * blue) / 0.7152
    linear = np.power(np.clip(np.stack([red, green, blue], -1), 0.0, None), 2.4)
    display = linear @ _BT709_TO_BT2020.T * _SDR_IN_HLG
    luminance = display @ np.array(_BT2020_LUMA)
    scene = display * np.power(np.maximum(luminance, 1e-12), 1.0 / _HLG_GAMMA - 1.0)[..., None]
    scene = np.clip(scene, 0.0, None)
    signal = np.where(
        scene <= 1.0 / 12.0,
        np.sqrt(3.0 * scene),
        _HLG_A * np.log(np.maximum(12.0 * scene - _HLG_B, 1e-12)) + _HLG_C,
    )
    return np.clip(np.rint(signal * 65535.0), 0, 65535).astype(np.uint16)


def hlg_frame_filter(plan: EncodingPlan) -> str:
    """What FFmpeg still does to an HLG title frame: the matrix and chroma steps.

    zscale writes the planar formats itself and leaves the others, P010 for one, to
    swscale from 4:4:4, as the full chain did.
    """
    via = "" if plan.pixel_format in _ZSCALE_WRITES else ",format=yuv444p16le"
    return (
        "zscale=pin=bt2020:p=bt2020:tin=arib-std-b67:t=arib-std-b67:min=gbr:m=bt2020nc"
        ":rin=full:r=tv,setparams=colorspace=bt2020nc:color_primaries=bt2020"
        f":color_trc=arib-std-b67{via},format={plan.pixel_format}"
    )


def title_frames_in_hlg(plan: EncodingPlan) -> SdrToHlg | None:
    """The conversion for this plan's title frames, or None to keep zscale on every frame.

    Only an HLG film qualifies; PQ uses an approximated curve on some machines.
    """
    if plan.target_transfer is not HdrTransfer.HLG:
        return None
    return _qualified(plan.pixel_format)


def _reference_picture() -> np.ndarray:
    """Gradients, saturated colours, hard edges and grain: what titles are made of."""
    rows, columns = np.mgrid[0:96, 0:128]
    picture = np.stack(
        [columns / 127.0, rows / 95.0, 0.5 + 0.5 * np.sin(columns / 9.0 + rows / 13.0)], -1
    )
    picture += np.random.default_rng(2709).normal(0.0, 0.02, picture.shape)
    picture[10:30, 10:60] = (1.0, 0.0, 0.0)
    picture[40:60, 20:100] = (0.0, 0.0, 1.0)
    picture[70:90, 30:110] = (1.0, 1.0, 1.0)
    picture[0:96:7, :] = (0.05, 0.9, 0.1)
    return np.clip(np.rint(np.clip(picture, 0.0, 1.0) * 65535.0), 0, 65535).astype(np.uint16)


def _ffmpeg(picture: np.ndarray, vf: str, pixel_format: str) -> np.ndarray:
    rows, columns = picture.shape[:2]
    result = subprocess.run(  # noqa: S603
        [
            "ffmpeg", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb48le",
            "-s", f"{columns}x{rows}", "-i", "pipe:0", "-vf", vf,
            "-f", "rawvideo", "-pix_fmt", pixel_format, "pipe:1",
        ],
        input=np.ascontiguousarray(picture).tobytes(), capture_output=True, timeout=30, check=True,
    )  # fmt: skip
    return np.frombuffer(result.stdout, dtype=np.uint16)


def _measured_coefficients(picture: np.ndarray) -> SdrToHlg:
    """swscale's RGB to Y'CbCr mapping on this FFmpeg, fitted plane by plane."""
    planes = _ffmpeg(picture, f"{RGB_TO_BT709_TV},format=yuv444p16le", "yuv444p16le").reshape(3, -1)
    rgb = picture.reshape(-1, 3).astype(np.float64) / 65535.0
    luma = rgb @ np.array((0.2126, 0.7152, 0.0722))
    fitted: list[float] = []
    for plane, signal in zip(
        planes, (luma, (rgb[:, 2] - luma) / 1.8556, (rgb[:, 0] - luma) / 1.5748), strict=True
    ):
        design = np.stack([signal, np.ones_like(signal)], -1)
        scale, offset = np.linalg.lstsq(design, plane.astype(np.float64), rcond=None)[0]
        fitted.extend((float(scale), float(offset)))
    return SdrToHlg(*fitted)


@cache
def _qualified(pixel_format: str) -> SdrToHlg | None:
    from immich_memories.titles.encoding import title_color_filter

    plan = EncodingPlan(
        codec=OutputCodec.H265,
        encoder="libx265",
        encoder_args=(),
        target_transfer=HdrTransfer.HLG,
        tone_map_to_sdr=False,
        pixel_format=pixel_format,
        container="mp4",
    )
    picture = _reference_picture()
    try:
        conversion = _measured_coefficients(picture)
        # Both chains end in the plan's format; read back as plain 10-bit codes.
        expected = _ffmpeg(picture, title_color_filter(plan), "yuv420p10le").astype(np.int64)
        actual = _ffmpeg(sdr_to_hlg(picture, conversion), hlg_frame_filter(plan), "yuv420p10le")
    except (OSError, subprocess.SubprocessError, ValueError, np.linalg.LinAlgError) as exc:
        logger.info("HLG title frames keep FFmpeg's conversion: %s", exc)
        return None
    worst = int(np.abs(actual.astype(np.int64) - expected).max()) if expected.size else -1
    if expected.size == 0 or expected.size != actual.size or worst > _MAX_CODE_DIFFERENCE:
        logger.info("HLG title frames keep FFmpeg's conversion (differs by %d codes)", worst)
        return None
    return conversion


def finalize_to_hlg(
    frame,
    output,
    conversion: SdrToHlg,
    *,
    fade_in: float = 1.0,
    fade_out: float = 0.0,
    fade_color: str = "white",
) -> None:
    """``finalize_to_output`` for an HLG film: the frame leaves the device already in HLG."""
    from immich_memories.titles.gpu_kernel_backend import ti

    global _finalize_hlg  # noqa: PLW0603
    if _finalize_hlg is None:
        from immich_memories.titles.hlg_kernel import compile_hlg_finalize

        _finalize_hlg = compile_hlg_finalize(
            _BT709_TO_BT2020,
            _BT2020_LUMA,
            _SDR_IN_HLG,
            1.0 / _HLG_GAMMA - 1.0,
            (_HLG_A, _HLG_B, _HLG_C),
        )
    edge = 0.0 if fade_color == "black" else 65535.0
    coefficients = _device_coefficients(conversion, ti)
    _finalize_hlg(
        frame,
        output,
        fade_in,
        int(edge * (1.0 - fade_in)),
        1.0 - fade_out,
        int(edge * fade_out),
        coefficients,
    )


_finalize_hlg: Callable[..., None] | None = None


@cache
def _device_coefficients(conversion: SdrToHlg, ti):
    coefficients = ti.ndarray(dtype=ti.f32, shape=(6,))
    coefficients.from_numpy(
        np.array(
            [
                conversion.luma_scale,
                conversion.luma_offset,
                conversion.blue_scale,
                conversion.blue_offset,
                conversion.red_scale,
                conversion.red_offset,
            ],
            dtype=np.float32,
        )
    )
    return coefficients
