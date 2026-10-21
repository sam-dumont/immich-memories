"""The decode-to-canvas half of a clip's filter graph, run on the GPU.

A clip decoded on an NVIDIA card (CUDA) or a Mac (VideoToolbox) stays in GPU
memory while it is scaled to the canvas, turned upright and, for a blur fill,
while its background is shrunk and blown back up. Frames reach system memory
once, at canvas size or smaller, in the format the film's pipe and encoder take.

Only the work no GPU filter on these builds reproduces stays on the CPU, at the
smallest size it can run at: the Gaussian of the blur fill (on a frame a quarter
of the canvas wide), transfer conversions (zscale's HLG/PQ/SDR maths; the
tonemap_opencl and scale_vt conversions land 9 to 26 code values away from it on
the Dolby Vision fixture) and, on CUDA, which has no transpose, the turn of an
upright-recorded phone video after it was scaled down.
"""

from __future__ import annotations

import functools
import logging
import subprocess
from dataclasses import dataclass
from math import ceil
from typing import TYPE_CHECKING, Literal

from immich_memories.processing.hardware_decode_check import hardware_decode_matches

if TYPE_CHECKING:
    from pathlib import Path

    from immich_memories.processing.hardware import HWAccelCapabilities
    from immich_memories.processing.probe_cache import ProbeCache, VideoProbe

logger = logging.getLogger(__name__)

GpuBackend = Literal["cuda", "videotoolbox"]

# The codecs and 4:2:0 layouts both decoders hand back in GPU memory. H.264 High 10
# (the app's own HDR still moves) has no hardware decoder, so it stays in software.
_GPU_DECODED = {("h264", "yuv420p"), ("hevc", "yuv420p"), ("hevc", "yuv420p10le")}

_HWACCEL_ARGS: dict[GpuBackend, tuple[str, ...]] = {
    "cuda": (
        "-init_hw_device", "cuda=gpu", "-filter_hw_device", "gpu",
        "-hwaccel", "cuda", "-hwaccel_device", "gpu", "-hwaccel_output_format", "cuda",
    ),
    "videotoolbox": (
        "-init_hw_device", "videotoolbox=gpu", "-filter_hw_device", "gpu",
        "-hwaccel", "videotoolbox", "-hwaccel_device", "gpu",
        "-hwaccel_output_format", "videotoolbox_vld",
    ),
}  # fmt: skip

_VT_TURNS = {
    90: "transpose_vt=dir=clock",
    180: "transpose_vt=dir=reversal",
    270: "transpose_vt=dir=cclock",
}
_CPU_TURNS = {90: "transpose=clock", 180: "hflip,vflip", 270: "transpose=cclock"}


def _even(value: float) -> int:
    return max(2, int(value) // 2 * 2)


@dataclass(frozen=True)
class GpuFrameGraph:
    """How one clip is decoded and brought to the canvas on the GPU."""

    backend: GpuBackend
    coded_size: tuple[int, int]
    # The clockwise turn that shows the picture upright (the display matrix).
    turn: int
    ten_bit: bool
    # The source's colour tags. A frame uploaded back to the GPU comes down without
    # them, and the strips it lends the stack would leave the stacked frame untagged.
    color_tags: tuple[str, str] | None = None

    def hwaccel_args(self) -> tuple[str, ...]:
        """Input options that decode into GPU memory; FFmpeg's autorotate is ours to do."""
        return (*_HWACCEL_ARGS[self.backend], "-noautorotate")

    def gpu_format(self, ten_bit: bool) -> str:
        """The software layout of a GPU frame: P010 for 10-bit, else 8-bit 4:2:0."""
        if ten_bit:
            return "p010le"
        return "yuv420p" if self.backend == "cuda" else "nv12"

    def download_format(self) -> str:
        """The layout this clip's frames reach system memory in."""
        return self.gpu_format(self.ten_bit)

    def display_size(self) -> tuple[int, int]:
        width, height = self.coded_size
        return (height, width) if self.turn in (90, 270) else (width, height)

    def fill(
        self,
        canvas: tuple[int, int],
        scale_mode: str,
        *,
        convert_first: str = "",
        converted_ten_bit: bool | None = None,
    ) -> str:
        """Filters from decoded GPU frames to a canvas-sized frame in system memory.

        ``convert_first`` runs a CPU transfer conversion on the source-sized frame
        before it goes back up for scaling: worth one small upload when the source
        has fewer pixels than the canvas, where converting after scaling would
        touch every canvas pixel.
        """
        ten_bit = self.ten_bit
        head = ""
        if convert_first:
            ten_bit = self.ten_bit if converted_ten_bit is None else converted_ten_bit
            planar = "yuv420p10le" if ten_bit else "yuv420p"
            # Decoded surfaces are NV12 or P010 until a GPU scale converts them.
            decoded = "p010le" if self.ten_bit else "nv12"
            head = (
                f"hwdownload,format={decoded},{convert_first},format={planar},"
                f"format={self.gpu_format(ten_bit)},hwupload,"
            )
        return head + self._fill(canvas, scale_mode, ten_bit)

    def _fill(self, canvas: tuple[int, int], scale_mode: str, ten_bit: bool) -> str:
        width, height = canvas
        display_w, display_h = self.display_size()
        if display_w * height == display_h * width:
            return self._sized((width, height), ten_bit, "lanczos")
        if display_w * height < width * display_h:
            fitted = (_even(display_w * height / display_h), height)
        else:
            fitted = (width, _even(display_h * width / display_w))
        if scale_mode != "blur":
            x, y = (width - fitted[0]) // 4 * 2, (height - fitted[1]) // 4 * 2
            sharp = self._sized(fitted, ten_bit, "lanczos")
            return f"{sharp},pad={width}:{height}:{x}:{y}:black"
        return self._blur_fill(canvas, fitted, ten_bit)

    def _blur_fill(self, canvas: tuple[int, int], fitted: tuple[int, int], ten_bit: bool) -> str:
        """The sharp picture between two strips of its own blurred, enlarged background.

        Stacking the strips beside the picture replaces a canvas-sized overlay,
        and keeps P010 frames P010: the CPU overlay only composites planar formats.
        """
        width, height = canvas
        factor = 4 if min(canvas) >= 2160 else 2
        if min(canvas) < 1080 or width % (2 * factor) or height % (2 * factor):
            factor = 1
        small_w, small_h = width // factor, height // factor
        display_w, display_h = self.display_size()
        cover = max(small_w / display_w, small_h / display_h)
        covering = (_even(ceil(display_w * cover) + 1), _even(ceil(display_h * cover) + 1))
        frame_format = self.gpu_format(ten_bit)
        planar = "yuv420p10le" if ten_bit else "yuv420p"
        background = (
            f"[_gbg]{self._sized(covering, ten_bit, 'lanczos')},format={planar},"
            f"crop={small_w}:{small_h}:exact=1,gblur=sigma={30 / factor:g},format={frame_format}"
        )
        if factor > 1:
            background += (
                f",hwupload,{self._scale((width, height), ten_bit, 'bilinear')},"
                f"{self._download(ten_bit)}"
            )
        sharp = f"[_gfg]{self._sized(fitted, ten_bit, 'lanczos')}[_gsharp]"
        if fitted[0] < width:
            before = (width - fitted[0]) // 4 * 2
            pieces = [
                (before, height, 0, 0),
                (width - fitted[0] - before, height, before + fitted[0], 0),
            ]
            stack = "hstack"
        else:
            before = (height - fitted[1]) // 4 * 2
            pieces = [
                (width, before, 0, 0),
                (width, height - fitted[1] - before, 0, before + fitted[1]),
            ]
            stack = "vstack"
        strips = [piece for piece in pieces if piece[0] > 0 and piece[1] > 0]
        labels = [f"[_gstrip{index}]" for index in range(len(strips))]
        chains = [
            "split[_gbg][_gfg]",
            f"{background},split={len(strips)}{''.join(labels)}"
            if len(strips) > 1
            else f"{background}{labels[0]}",
        ]
        chains += [
            f"{label}crop={w}:{h}:{x}:{y}:exact=1{label.replace('strip', 'piece')}"
            for label, (w, h, x, y) in zip(labels, strips, strict=True)
        ]
        order = [label.replace("strip", "piece") for label in labels]
        if before > 0:
            order.insert(1, "[_gsharp]")
        else:
            order.insert(0, "[_gsharp]")
        restored = ""
        if self.color_tags is not None:
            restored = (
                f",setparams=color_primaries={self.color_tags[0]}:color_trc={self.color_tags[1]}"
            )
        # WHY (#2792): the CPU blur fill's negotiated output format left libplacebo,
        # next in the chain, with a graph that never output a frame; this one is
        # pinned the same way.
        pinned = f",format={frame_format}"
        chains += [sharp, f"{''.join(order)}{stack}=inputs={len(order)}{pinned}{restored}"]
        return ";".join(chains)

    def _sized(self, size: tuple[int, int], ten_bit: bool, quality: str) -> str:
        """Scale to a display-oriented size, turn upright and download."""
        width, height = size
        coded = (height, width) if self.turn in (90, 270) else (width, height)
        # VideoToolbox resamples chroma even at the same size; a source already at
        # the canvas size skips it. scale_cuda passes such frames through untouched,
        # and is what turns an 8-bit NV12 surface into planar yuv420p on the GPU.
        unscaled = self.backend == "videotoolbox" and coded == self.coded_size
        parts = [] if unscaled else [self._scale(coded, ten_bit, quality)]
        if self.backend == "videotoolbox" and self.turn in _VT_TURNS:
            parts.append(_VT_TURNS[self.turn])
        parts.append(self._download(ten_bit))
        if self.backend == "cuda" and self.turn in _CPU_TURNS:
            # No CUDA transpose ships with FFmpeg; the turn runs on the scaled frame.
            parts.append(_CPU_TURNS[self.turn])
        return ",".join(parts)

    def _scale(self, size: tuple[int, int], ten_bit: bool, quality: str) -> str:
        width, height = size
        if self.backend == "cuda":
            return (
                f"scale_cuda={width}:{height}:interp_algo={quality}"
                f":format={self.gpu_format(ten_bit)}"
            )
        return f"scale_vt=w={width}:h={height}"

    def _download(self, ten_bit: bool) -> str:
        return f"hwdownload,format={self.gpu_format(ten_bit)}"


def gpu_backend(capabilities: HWAccelCapabilities | None) -> GpuBackend | None:
    """The GPU filter family this machine's decoder belongs to, if it has one."""
    from immich_memories.processing.hardware import HWAccelBackend

    if capabilities is None:
        return None
    if capabilities.backend == HWAccelBackend.NVIDIA:
        return "cuda"
    if capabilities.backend == HWAccelBackend.APPLE:
        return "videotoolbox"
    return None


# The 4:2:0 formats hardware decoders hand back as NV12 or P010. A format filter
# repacks those into exactly the software decoder's frames, so every filter after it
# sees the same pixels whichever decoder ran (#2709).
_HARDWARE_DECODED_FORMATS = frozenset({"yuv420p", "yuv420p10le"})
_HARDWARE_DECODED_CODECS = {"h264": "h264", "hevc": "h265"}


def hardware_decode_for(
    path: Path, capabilities: HWAccelCapabilities | None, probe_cache: ProbeCache
) -> tuple[tuple[str, ...], str] | None:
    """The hwaccel arguments for decoding ``path``, and the format its frames are repacked to.

    None decodes in software: no capable hardware, a codec or format the hardware
    decoders cannot hand back exactly, or a source the probe cannot read.
    """
    from immich_memories.processing.hardware import get_ffmpeg_hwaccel_args
    from immich_memories.processing.probe_cache import ProbeError

    if capabilities is None:
        return None
    try:
        probe = probe_cache.get(path)
    except (ProbeError, OSError, ValueError):
        return None
    codec = _HARDWARE_DECODED_CODECS.get(probe.codec)
    if codec is None or probe.pixel_format not in _HARDWARE_DECODED_FORMATS:
        return None
    supported = (
        capabilities.supports_h264_decode if codec == "h264" else capabilities.supports_h265_decode
    )
    args = get_ffmpeg_hwaccel_args(
        capabilities, operation="decode", codec=codec, for_software_filters=True
    )
    if not supported or not args:
        return None
    if not hardware_decode_matches(tuple(args), codec, str(probe.pixel_format)):
        return None
    return tuple(args), str(probe.pixel_format)


def _hardware_decoder_trusted(probe: VideoProbe, capabilities: HWAccelCapabilities) -> bool:
    """Whether the GPU graph's decoder gives the software picture for this clip's codec."""
    from immich_memories.processing.hardware import get_ffmpeg_hwaccel_args

    # Only called for the codecs in _GPU_DECODED, which all have a name here.
    codec = _HARDWARE_DECODED_CODECS[probe.codec]
    args = get_ffmpeg_hwaccel_args(
        capabilities, operation="decode", codec=codec, for_software_filters=True
    )
    return bool(args) and hardware_decode_matches(tuple(args), codec, str(probe.pixel_format))


def gpu_frame_graph_for(
    probe: VideoProbe, capabilities: HWAccelCapabilities | None
) -> GpuFrameGraph | None:
    """The GPU graph for a clip, or None when any part of it would not run on the GPU."""
    backend = gpu_backend(capabilities)
    if backend is None or capabilities is None:
        return None
    if (probe.codec, probe.pixel_format) not in _GPU_DECODED:
        return None
    if not (
        capabilities.supports_h264_decode
        if probe.codec == "h264"
        else capabilities.supports_h265_decode
    ):
        return None
    if probe.display_turn not in (0, 90, 180, 270) or probe.width <= 0 or probe.height <= 0:
        return None
    if not gpu_filters_work(backend) or not _hardware_decoder_trusted(probe, capabilities):
        return None
    tags = (probe.color_primaries, probe.color_transfer)
    return GpuFrameGraph(
        backend=backend,
        coded_size=(probe.width, probe.height),
        turn=probe.display_turn,
        ten_bit=probe.pixel_format == "yuv420p10le",
        color_tags=(tags[0], tags[1]) if tags[0] and tags[1] else None,
    )


def gpu_frame_graph_for_path(
    path, capabilities: HWAccelCapabilities | None, probe_cache: ProbeCache
) -> GpuFrameGraph | None:
    """``gpu_frame_graph_for`` on a file; an unreadable probe decodes in software."""
    from immich_memories.processing.probe_cache import ProbeError

    if gpu_backend(capabilities) is None:
        return None
    try:
        probe = probe_cache.get(path)
    except (ProbeError, OSError, ValueError):
        return None
    return gpu_frame_graph_for(probe, capabilities)


# Every filter the graphs above use, on frames uploaded from a synthetic source:
# the same device setup a clip gets, so a build or driver without one of them
# keeps every clip on the CPU path instead of failing the film.
_PROBE_GRAPHS: dict[GpuBackend, str] = {
    "cuda": (
        "split[a][b];"
        "[a]format=p010le,hwupload,scale_cuda=128:72:interp_algo=lanczos:format=p010le,"
        "scale_cuda=256:144:interp_algo=bilinear:format=p010le,hwdownload,format=p010le[x];"
        "[b]format=yuv420p,hwupload,scale_cuda=256:144:interp_algo=lanczos:format=yuv420p,"
        "hwdownload,format=yuv420p,format=p010le[y];[x][y]vstack"
    ),
    "videotoolbox": (
        "split[a][b];"
        "[a]format=p010le,hwupload,scale_vt=w=144:h=256,transpose_vt=dir=clock,"
        "hwdownload,format=p010le[x];"
        "[b]format=nv12,hwupload,scale_vt=w=256:h=144,hwdownload,format=nv12,format=p010le[y];"
        "[x][y]vstack"
    ),
}


@functools.cache
def gpu_filters_work(backend: GpuBackend) -> bool:
    """Whether this FFmpeg and device run the GPU filter graph; asked once a process."""
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
        *_HWACCEL_ARGS[backend][:4],
        "-f", "lavfi", "-i", "testsrc2=size=256x144:rate=1",
        "-filter_complex", _PROBE_GRAPHS[backend],
        "-frames:v", "1", "-f", "null", "-",
    ]  # fmt: skip
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("GPU filter probe for %s could not run: %s", backend, exc)
        return False
    if result.returncode != 0:
        logger.info(
            "GPU filters unavailable on %s; clips are scaled on the CPU (%s)",
            backend,
            result.stderr.strip().splitlines()[-1:] or "no output",
        )
        return False
    logger.info("Clips are scaled and composed on the GPU (%s)", backend)
    return True
