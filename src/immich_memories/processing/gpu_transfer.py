"""Transfer conversions on the GPU: libplacebo running zscale's own maths.

Tone mapping HDR to SDR was the largest CPU cost left in a render: about 76 s
of CPU for 6 s of 4K on the render worker. FFmpeg's GPU tone mappers do not
give zscale's picture (`tonemap_opencl` darkens each frame by the scene's
average brightness, with no way to turn that off; VideoToolbox uses Apple's
curve), so the GPU runs a user shader through libplacebo that is the CPU
chain's maths: zimg's transfer functions, the `tonemap` filter's hable curve on
the largest channel, the same primaries matrix. libplacebo only turns Y'CbCr
into RGB and back. The same goes for SDR to HLG or PQ and between HLG and PQ.

FFmpeg needs libplacebo and a Vulkan device. Ubuntu's FFmpeg has both on an
NVIDIA card whose container has the `graphics` driver capability; on a Mac, an
FFmpeg built with libplacebo (Homebrew's `ffmpeg-full`) runs it on MoltenVK.
Pixels qualify it, not versions: one frame per process goes through both
chains, and an FFmpeg, driver or device whose picture strays keeps zscale.
"""

from __future__ import annotations

import atexit
import functools
import hashlib
import json
import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# CIE xy of each primaries set a source may carry; all share the D65 white.
_CHROMATICITIES = {
    "bt709": ((0.640, 0.330), (0.300, 0.600), (0.150, 0.060)),
    "bt2020": ((0.708, 0.292), (0.170, 0.797), (0.131, 0.046)),
    "smpte432": ((0.680, 0.320), (0.265, 0.690), (0.150, 0.060)),
    "bt470bg": ((0.640, 0.330), (0.290, 0.600), (0.150, 0.060)),
    "smpte170m": ((0.630, 0.340), (0.310, 0.595), (0.155, 0.070)),
}
_D65 = (0.3127, 0.3290)
# zscale reads an SDR source with this matrix (`min=` in hdr_utilities).
_SDR_MATRIX = {
    "bt709": "bt709",
    "smpte432": "bt709",
    "bt470bg": "bt470bg",
    "smpte170m": "smpte170m",
}
# Reference white: 100 nits for tone mapping (`npl=100`), 203 for SDR in HDR.
_TONE_MAP_WHITE = 100.0
_HDR_WHITE = 203.0
# The `tonemap` filter's default signal peak for an HLG or linear source.
_DEFAULT_PEAK = 10.0

_FUNCTIONS = """
const float HLG_A = 0.17883277;
const float HLG_B = 0.28466892;
const float HLG_C = 0.55991073;
const float PQ_M1 = 0.1593017578125;
const float PQ_M2 = 78.84375;
const float PQ_C1 = 0.8359375;
const float PQ_C2 = 18.8515625;
const float PQ_C3 = 18.6875;
const float FLT_MIN = 1.175494e-38;

float hlg_inverse_oetf(float x) {
    x = max(x, 0.0);
    return x <= 0.5 ? x * x / 3.0 : (exp((x - HLG_C) / HLG_A) + HLG_B) / 12.0;
}
float hlg_oetf(float x) {
    x = max(x, 0.0);
    return x <= 1.0 / 12.0 ? sqrt(3.0 * x) : HLG_A * log(12.0 * x - HLG_B) + HLG_C;
}
float pq_eotf(float x) {
    if (x <= 0.0) return 0.0;
    float p = pow(x, 1.0 / PQ_M2);
    return pow(max(p - PQ_C1, 0.0) / max(PQ_C2 - PQ_C3 * p, FLT_MIN), 1.0 / PQ_M1);
}
float pq_inverse_eotf(float x) {
    if (x <= 0.0) return 0.0;
    float p = pow(x, PQ_M1);
    return pow(1.0 + ((PQ_C1 - 1.0) + (PQ_C2 - PQ_C3) * p) / (1.0 + PQ_C3 * p), PQ_M2);
}
float hable(float x) {
    return (x * (x * 0.15 + 0.05) + 0.004) / (x * (x * 0.15 + 0.50) + 0.06) - 0.02 / 0.30;
}
vec3 per_channel_hlg(vec3 c) {
    return vec3(hlg_inverse_oetf(c.r), hlg_inverse_oetf(c.g), hlg_inverse_oetf(c.b));
}
"""


def _rgb_to_xyz(primaries: str) -> np.ndarray:
    xyz = np.array([[x / y, 1.0, (1.0 - x - y) / y] for x, y in _CHROMATICITIES[primaries]]).T
    white_x, white_y = _D65
    white = np.array([white_x / white_y, 1.0, (1.0 - white_x - white_y) / white_y])
    return xyz * np.linalg.solve(xyz, white)


def _gamut(source: str, target: str) -> np.ndarray:
    """Linear-light RGB in ``source`` primaries to ``target``, as zimg derives it."""
    return np.linalg.inv(_rgb_to_xyz(target)) @ _rgb_to_xyz(source)


def _vec3(values) -> str:
    return "vec3(" + ", ".join(f"{float(v):.10f}" for v in values) + ")"


def _mat3(matrix: np.ndarray) -> str:
    # GLSL fills a mat3 column by column.
    return "mat3(" + ", ".join(f"{matrix[r][c]:.10f}" for c in range(3) for r in range(3)) + ")"


def _hable(x: float) -> float:
    return (x * (x * 0.15 + 0.05) + 0.004) / (x * (x * 0.15 + 0.50) + 0.06) - 0.02 / 0.30


@dataclass(frozen=True)
class TransferConversion:
    """One clip's transfer conversion, as `hdr_utilities.get_hdr_conversion_filter` builds it."""

    source: str  # "hlg", "pq" or "sdr"
    target: str
    source_primaries: str = "bt709"
    # The tone map's signal peak in units of 100 nits (`signal_peak`).
    peak: float = _DEFAULT_PEAK

    @property
    def supported(self) -> bool:
        if self.source == self.target or {self.source, self.target} - {"hlg", "pq", "sdr"}:
            return False
        return self.source != "sdr" or self.source_primaries in _SDR_MATRIX

    @property
    def _white(self) -> float:
        return _TONE_MAP_WHITE if self.target == "sdr" else _HDR_WHITE

    def shader(self) -> str:
        """The mpv-style user shader libplacebo runs on each frame's RGB."""
        source_primaries = self.source_primaries if self.source == "sdr" else "bt2020"
        target_primaries = "bt709" if self.target == "sdr" else "bt2020"
        steps = [*self._to_linear()]
        if self.target == "sdr":
            # The `tonemap` filter: hable on the largest channel, every channel scaled alike.
            steps += [
                "float sig = max(max(rgb.r, max(rgb.g, rgb.b)), 1e-6);",
                f"rgb *= (hable(sig) / {_hable(self.peak):.10f}) / sig;",
            ]
        if source_primaries != target_primaries:
            steps.append(f"rgb = {_mat3(_gamut(source_primaries, target_primaries))} * rgb;")
        steps += self._from_linear()
        body = "\n    ".join(steps)
        return (
            "//!HOOK MAIN\n//!BIND HOOKED\n//!DESC immich-memories transfer conversion\n"
            f"{_FUNCTIONS}\nvec4 hook() {{\n    vec4 color = HOOKED_texOff(0);\n"
            f"    vec3 rgb = color.rgb;\n    {body}\n    color.rgb = rgb;\n    return color;\n}}\n"
        )

    def _to_linear(self) -> list[str]:
        luma = _rgb_to_xyz("bt2020")[1]
        if self.source == "sdr":
            # BT.1886 with an ideal black: zimg's display-referred BT.709.
            return ["rgb = pow(max(rgb, 0.0), vec3(2.4));"]
        if self.source == "pq":
            return [
                "rgb = vec3(pq_eotf(rgb.r), pq_eotf(rgb.g), pq_eotf(rgb.b));",
                f"rgb *= {10000.0 / self._white:.10f};",
            ]
        if self.target == "sdr":
            # zscale's tone-map step keeps approximate gamma, which is zimg's per-channel OOTF.
            return [
                "rgb = pow(per_channel_hlg(rgb), vec3(1.2));",
                f"rgb *= {1000.0 / self._white:.10f};",
            ]
        return [
            "rgb = per_channel_hlg(rgb);",
            f"rgb *= pow(max(dot(rgb, {_vec3(luma)}), FLT_MIN), 0.2) * {1000.0 / self._white:.10f};",
        ]

    def _from_linear(self) -> list[str]:
        if self.target == "sdr":
            return ["rgb = pow(max(rgb, 0.0), vec3(1.0 / 2.4));"]
        if self.target == "pq":
            return [
                f"rgb *= {self._white / 10000.0:.10f};",
                "rgb = vec3(pq_inverse_eotf(rgb.r), pq_inverse_eotf(rgb.g), pq_inverse_eotf(rgb.b));",
            ]
        luma = _rgb_to_xyz("bt2020")[1]
        return [
            f"rgb *= {self._white / 1000.0:.10f};",
            f"rgb *= pow(max(dot(rgb, {_vec3(luma)}), FLT_MIN), -0.2 / 1.2);",
            "rgb = vec3(hlg_oetf(rgb.r), hlg_oetf(rgb.g), hlg_oetf(rgb.b));",
        ]

    def filter_chain(self, shader_path: Path, output_format: str) -> str:
        """The FFmpeg filters that replace zscale's chain, software frames in and out."""
        source_matrix = _SDR_MATRIX[self.source_primaries] if self.source == "sdr" else "bt2020nc"
        # zscale is told how to read the source (`rin`, `min`); libplacebo reads frame tags.
        read_as = f"colorspace={source_matrix}"
        if "sdr" in (self.source, self.target):
            read_as += ":range=tv"
        if self.target == "sdr":
            tags, matrix = ("bt709", "bt709", "bt709"), "bt709"
        else:
            transfer = "arib-std-b67" if self.target == "hlg" else "smpte2084"
            tags, matrix = ("bt2020", transfer, "bt2020nc"), "bt2020nc"
        output_range = ":range=tv" if "sdr" in (self.source, self.target) else ""
        return (
            # Mastering and dynamic metadata would have libplacebo map between peaks itself.
            f"sidedata=mode=delete,setparams={read_as},"
            f"libplacebo=custom_shader_path={shader_path}:apply_dolbyvision=0:apply_filmgrain=0"
            ":upscaler=bilinear:downscaler=bilinear:peak_detect=0:tonemapping=clip"
            f":gamut_mode=clip:dithering=none:colorspace={matrix}{output_range}"
            f":format={output_format},"
            f"setparams=color_primaries={tags[0]}:color_trc={tags[1]}:colorspace={tags[2]}"
        )


@functools.cache
def _shader_directory() -> Path:
    directory = Path(tempfile.mkdtemp(prefix="immich-memories-shaders-"))
    atexit.register(shutil.rmtree, directory, ignore_errors=True)
    return directory


def _shader_file(conversion: TransferConversion) -> Path | None:
    """The shader on disk for FFmpeg to read; None where the path could not sit in a filter."""
    text = conversion.shader()
    directory = _shader_directory()
    path = directory / f"{hashlib.sha256(text.encode()).hexdigest()[:20]}.glsl"
    # A filter-graph option value cannot hold these unescaped.
    if any(character in str(path) for character in ":,;[]'\\= "):
        return None
    if not path.exists():
        staged = path.with_suffix(".part")
        staged.write_text(text)
        staged.replace(path)
    return path


def gpu_conversion_filter(conversion: TransferConversion, output_format: str) -> str:
    """The GPU chain for ``conversion``, or "" to keep zscale."""
    if not conversion.supported or not gpu_transfer_works():
        return ""
    path = _shader_file(conversion)
    return "" if path is None else "," + conversion.filter_chain(path, output_format)


@functools.lru_cache(maxsize=512)
def signal_peak(path: Path) -> float:
    """The `tonemap` filter's signal peak for this file, in units of 100 nits.

    The filter reads it from each frame: the content light level, else the
    mastering display's peak, else 10 (a 1000-nit HLG display). Encoders repeat
    that metadata on every frame, so the first one speaks for the clip.
    """
    command = [
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-read_intervals", "%+#1",
        "-show_frames", "-show_entries", "frame_side_data=max_content,max_luminance",
        "-of", "json", str(path),
    ]  # fmt: skip
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=20, check=True)
        frames = json.loads(result.stdout).get("frames") or [{}]
    except (OSError, subprocess.SubprocessError, ValueError):
        return _DEFAULT_PEAK
    content = mastering = 0.0
    for entry in frames[0].get("side_data_list", []):
        content = content or float(entry.get("max_content") or 0)
        luminance = str(entry.get("max_luminance") or "0")
        numerator, _, denominator = luminance.partition("/")
        mastering = mastering or float(numerator) / float(denominator or 1)
    if content > 0:
        return content / _TONE_MAP_WHITE
    if mastering > 0:
        return mastering / _TONE_MAP_WHITE
    return _DEFAULT_PEAK


# Larger than what GPU and CPU floats disagree on, smaller than anything seen.
_MAX_MEAN_DIFFERENCE = 1.0
_MAX_DIFFERENCE = 8


def _probe_case(conversion: TransferConversion, source: str, cpu_chain: str) -> bool:
    ten_bit = conversion.target != "sdr"
    planar = "yuv420p10le" if ten_bit else "yuv420p"
    shader = _shader_file(conversion)
    if shader is None:
        return False
    graph = (
        f"[0:v]{source},split[cpu][gpu];[cpu]{cpu_chain},format={planar}[a];"
        f"[gpu]{conversion.filter_chain(shader, planar)}[b];[a][b]vstack,format={planar}"
    )
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
        "-f", "lavfi", "-i", "gradients=size=256x144:rate=1:seed=7",
        "-filter_complex", graph, "-frames:v", "1", "-f", "rawvideo", "-",
    ]  # fmt: skip
    try:
        result = subprocess.run(command, capture_output=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("GPU transfer probe could not run: %s", exc)
        return False
    if result.returncode != 0:
        logger.info(
            "No GPU transfer conversions here (%s); zscale converts on the CPU",
            result.stderr.decode(errors="replace").strip().splitlines()[-1:] or "no output",
        )
        return False
    samples = np.frombuffer(result.stdout, np.uint16 if ten_bit else np.uint8).astype(np.int32)
    width, height = 256, 144
    half = width * height * 3 // 2
    if samples.size != 2 * half:
        return False
    # vstack doubles each plane's height: plane by plane, the CPU rows come first.
    planes = (width * height * 2, width * height // 2, width * height // 2)
    offset, worst, means = 0, 0.0, []
    for size in planes:
        plane = samples[offset : offset + size]
        cpu, gpu = plane[: size // 2], plane[size // 2 :]
        difference = np.abs(cpu - gpu) / (4 if ten_bit else 1)
        worst = max(worst, float(difference.max()))
        means.append(float(difference.mean()))
        offset += size
    matched = max(means) <= _MAX_MEAN_DIFFERENCE and worst <= _MAX_DIFFERENCE
    logger.debug(
        "GPU %s-to-%s against zscale: mean %.2f, worst %.0f",
        conversion.source,
        conversion.target,
        max(means),
        worst,
    )
    if not matched:
        logger.info(
            "GPU transfer conversion strays from zscale (mean %.2f, worst %.0f); keeping zscale",
            max(means),
            worst,
        )
    return matched


@functools.cache
def gpu_transfer_works() -> bool:
    """Whether libplacebo on this machine's GPU gives zscale's picture; asked once a process."""
    from immich_memories.processing.hdr_utilities import (
        check_zscale_available,
        get_hdr_conversion_filter,
    )

    if not check_zscale_available():
        return False
    hlg = "format=yuv420p10le,setparams=range=tv:colorspace=bt2020nc:color_primaries=bt2020:color_trc=arib-std-b67"
    sdr = "format=yuv420p,setparams=range=tv:colorspace=bt709:color_primaries=bt709:color_trc=bt709"
    cases = (
        (TransferConversion("hlg", "sdr"), hlg, get_hdr_conversion_filter("hlg", "sdr")),
        (TransferConversion("sdr", "hlg"), sdr, get_hdr_conversion_filter("sdr", "hlg", "bt709")),
    )
    works = all(
        _probe_case(conversion, source, chain.removeprefix(","))
        for conversion, source, chain in cases
    )
    if works:
        logger.info("Tone mapping and transfer conversions run on the GPU (libplacebo)")
    return works


def gpu_conversion_for_clip(
    path: Path, clip_idx: int, ctx: object, hdr_type: str | None, pipe_format: str
) -> str:
    """The GPU chain for one clip of a film, or "" to keep zscale.

    The chain hands frames on in the layout the decoder's pipe takes where it can
    (P010 for a hardware encoder), so no CPU repack follows it.
    """
    from immich_memories.processing.hdr_utilities import clip_transfer

    source, target, primaries = clip_transfer(clip_idx, ctx, hdr_type)
    source = source if source in ("hlg", "pq") else "sdr"
    if source == target:
        return ""
    peak = signal_peak(Path(path)) if target == "sdr" else _DEFAULT_PEAK
    conversion = TransferConversion(source, target, primaries or "bt709", peak)
    if target == "sdr":
        output_format = "yuv420p"
    else:
        output_format = pipe_format if pipe_format in ("yuv420p10le", "p010le") else "yuv420p10le"
    return gpu_conversion_filter(conversion, output_format)


def transfer_conversion(
    zscale_chain: str,
    path: Path,
    clip_idx: int,
    ctx: object,
    hdr_type: str | None,
    pipe_format: str,
) -> str:
    """The clip's conversion: the GPU chain where it runs, else ``zscale_chain`` as given."""
    if not zscale_chain:
        return ""
    return gpu_conversion_for_clip(path, clip_idx, ctx, hdr_type, pipe_format) or zscale_chain
