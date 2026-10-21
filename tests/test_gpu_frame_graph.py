"""Clips are scaled and composed on the GPU when the platform can, on the CPU otherwise.

A clip that decodes on CUDA or VideoToolbox stays in GPU memory through scaling,
the turn upright and the blur fill, and reaches system memory once at canvas size.
Anything the probe says this machine cannot run keeps the CPU chain, and HDR
frames cross the pipe as P010 when the encoder reads P010.
"""

from __future__ import annotations

import io
import re
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from immich_memories.processing import gpu_frame_graph, hdr_utilities
from immich_memories.processing.encoding_plan import (
    EncodingPlan,
    HdrTransfer,
    OutputCodec,
    hdr_pipe_format,
)
from immich_memories.processing.frame_preview import maybe_emit_preview
from immich_memories.processing.gpu_frame_graph import GpuFrameGraph, gpu_frame_graph_for
from immich_memories.processing.hardware import HWAccelBackend, HWAccelCapabilities
from immich_memories.processing.hdr_utilities import get_colorspace_filter
from immich_memories.processing.probe_cache import VideoProbe, _parse_video_probe
from immich_memories.processing.streaming_assembler import StreamingEncoder
from immich_memories.processing.streaming_frame_blender import FrameBlender
from immich_memories.processing.streaming_frame_decoder import make_decoder

NVIDIA = HWAccelCapabilities(
    backend=HWAccelBackend.NVIDIA, supports_h264_decode=True, supports_h265_decode=True
)
APPLE = HWAccelCapabilities(
    backend=HWAccelBackend.APPLE, supports_h264_decode=True, supports_h265_decode=True
)
VAAPI = HWAccelCapabilities(
    backend=HWAccelBackend.VAAPI, supports_h264_decode=True, supports_h265_decode=True
)


def _probe(
    codec: str = "hevc",
    pixel_format: str = "yuv420p10le",
    size: tuple[int, int] = (3840, 2160),
    turn: int = 0,
    transfer: str = "arib-std-b67",
    primaries: str = "bt2020",
) -> VideoProbe:
    return VideoProbe(
        duration_seconds=6.0, video_duration_seconds=6.0, width=size[0], height=size[1],
        fps=30.0, codec=codec, bitrate=0, size_bytes=0, color_transfer=transfer,
        color_primaries=primaries, bit_depth=10, rotation=turn, video_stream_index=0,
        has_video=True, has_audio=False, audio_codec=None, audio_bitrate=0,
        average_frame_rate="30/1", nominal_frame_rate="30/1", pixel_format=pixel_format,
        display_turn=turn,
    )  # fmt: skip


class _Probes:
    """The ffprobe boundary: what the probe says about every clip."""

    def __init__(self, probe: VideoProbe) -> None:
        self._probe = probe

    def get(self, _path):
        return self._probe


@pytest.fixture(autouse=True)
def zscale(monkeypatch):
    """Every conversion graph builds whether or not this host's FFmpeg has zscale."""
    # WHY: replaces the `ffmpeg -filters` run that checks the host build for zscale.
    monkeypatch.setattr(hdr_utilities, "check_zscale_available", lambda: True)


@pytest.fixture
def gpu_filters(monkeypatch):
    """Whether the GPU filter probe passes, set per test."""

    def answer(works: bool) -> None:
        # WHY: replaces the FFmpeg run that checks the device and its filters.
        monkeypatch.setattr(gpu_frame_graph, "gpu_filters_work", lambda _backend: works)
        # WHY: replaces the FFmpeg runs that compare the hardware decode with the software one.
        monkeypatch.setattr(gpu_frame_graph, "hardware_decode_matches", lambda *_args: True)

    return answer


@pytest.mark.parametrize(("capabilities", "backend"), [(NVIDIA, "cuda"), (APPLE, "videotoolbox")])
def test_a_clip_gets_the_gpu_graph_when_the_probe_says_it_runs(gpu_filters, capabilities, backend):
    gpu_filters(True)

    graph = gpu_frame_graph_for(_probe(), capabilities)

    assert graph is not None
    assert graph.backend == backend


@pytest.mark.parametrize(
    ("probe", "capabilities"),
    [
        (_probe(), VAAPI),
        (_probe(codec="h264", pixel_format="yuv420p10le"), NVIDIA),
        (_probe(codec="vp9", pixel_format="yuv420p"), NVIDIA),
        (_probe(pixel_format="yuv422p10le"), APPLE),
        (_probe(), None),
    ],
)
def test_clips_without_a_gpu_path_keep_the_cpu_chain(gpu_filters, probe, capabilities):
    gpu_filters(True)

    assert gpu_frame_graph_for(probe, capabilities) is None


def test_a_failed_probe_keeps_every_clip_on_the_cpu(gpu_filters):
    gpu_filters(False)

    assert gpu_frame_graph_for(_probe(), NVIDIA) is None


def test_a_decoder_that_strays_from_the_software_picture_keeps_the_clip_on_the_cpu(
    gpu_filters, monkeypatch
):
    gpu_filters(True)
    # WHY: replaces the FFmpeg runs; this decoder's frames differ from the software ones.
    monkeypatch.setattr(gpu_frame_graph, "hardware_decode_matches", lambda *_args: False)

    assert gpu_frame_graph_for(_probe(), APPLE) is None


def _context(capabilities, target: str = "hlg", source: str | None = "hlg"):
    return SimpleNamespace(
        hdr_type=target,
        pix_fmt="yuv420p10le" if target != "sdr" else "yuv420p",
        clip_hdr_types=[source],
        clip_primaries=["bt2020" if source else "bt709"],
        colorspace_filter=get_colorspace_filter(target),
        decode_capabilities=capabilities,
    )


def _decoder(probe: VideoProbe, ctx, *, canvas=(3840, 2160), privacy=False, pipe="p010le"):
    clip = SimpleNamespace(path=Path("clip.mov"), duration=6.0, is_title_screen=False)
    hdr = None if ctx.hdr_type == "sdr" else ctx.hdr_type
    return make_decoder(
        clip, 0, *canvas, 30, ctx, privacy, scale_mode="blur", hdr_type=hdr,
        probe_cache=_Probes(probe), planar_sdr=True, hdr_pipe_format=pipe,
    )  # fmt: skip


def test_the_decoder_scales_on_cuda_when_the_probe_passes(gpu_filters):
    gpu_filters(True)

    command = _decoder(_probe(turn=90), _context(NVIDIA))._command()

    assert command[command.index("-hwaccel_output_format") + 1] == "cuda"
    graph = command[command.index("-filter_complex") + 1]
    assert "scale_cuda=" in graph
    assert "overlay" not in graph
    assert "scale=3840" not in graph


def test_the_decoder_keeps_the_cpu_chain_when_the_probe_fails(gpu_filters):
    gpu_filters(False)

    command = _decoder(_probe(turn=90), _context(NVIDIA))._command()

    assert "-hwaccel_output_format" not in command
    graph = command[command.index("-filter_complex") + 1]
    assert "scale_cuda" not in graph
    assert "overlay=" in graph


def test_privacy_blur_is_shaped_on_the_cpu(gpu_filters):
    gpu_filters(True)

    graph = _decoder(_probe(), _context(NVIDIA), privacy=True)._build_vf()

    assert "scale_cuda" not in graph


def _strips(graph: str) -> list[tuple[int, int]]:
    return [(int(w), int(x)) for w, x in re.findall(r"crop=(\d+):2160:(\d+):0:exact=1", graph)]


def test_a_portrait_clip_sits_between_two_strips_of_its_blurred_background():
    graph = GpuFrameGraph("cuda", (3840, 2160), turn=90, ten_bit=True)

    fill = graph.fill((3840, 2160), "blur")

    # Scaled while still stored sideways, then turned upright on the small frame.
    assert "scale_cuda=2160:1214:interp_algo=lanczos:format=p010le,hwdownload" in fill
    assert "hwdownload,format=p010le,transpose=clock[_gsharp]" in fill
    (left, left_x), (right, right_x) = _strips(fill)
    assert left_x == 0 and left % 2 == 0 and right % 2 == 0
    assert left + 1214 + right == 3840
    assert right_x == left + 1214
    assert "[_gpiece0][_gsharp][_gpiece1]hstack=inputs=3" in fill


def test_videotoolbox_turns_the_clip_on_the_gpu():
    graph = GpuFrameGraph("videotoolbox", (3840, 2160), turn=90, ten_bit=True)

    fill = graph.fill((3840, 2160), "blur")

    assert "transpose_vt=dir=clock,hwdownload" in fill
    assert "transpose=clock" not in fill


def test_a_landscape_clip_in_a_portrait_canvas_stacks_vertically():
    fill = GpuFrameGraph("cuda", (1920, 1080), turn=0, ten_bit=False).fill((1080, 1920), "blur")

    assert "vstack=inputs=3" in fill
    assert "format=yuv420p[_gsharp]" in fill


def test_a_small_sdr_clip_is_converted_before_it_is_enlarged(gpu_filters):
    gpu_filters(True)
    probe = _probe(codec="h264", pixel_format="yuv420p", size=(1920, 1080), transfer="bt709",
                   primaries="bt709")  # fmt: skip

    graph = _decoder(probe, _context(NVIDIA, source=None))._build_vf()

    assert graph.index("hwdownload,format=nv12,zscale=") < graph.index("hwupload")
    assert graph.index("hwupload") < graph.index("scale_cuda=3840:2160")


def test_a_large_hdr_clip_is_tone_mapped_after_it_is_shrunk(gpu_filters):
    gpu_filters(True)

    graph = _decoder(_probe(), _context(NVIDIA, target="sdr"), canvas=(1920, 1080))._build_vf()

    assert graph.index("scale_cuda=1920:1080") < graph.index("tonemap=")


def test_the_display_turn_keeps_its_direction():
    def parsed(rotation: int) -> int:
        return _parse_video_probe(
            {"streams": [{"codec_type": "video", "side_data_list": [{"rotation": rotation}]}]}
        ).display_turn

    assert (parsed(-90), parsed(90), parsed(180)) == (90, 270, 180)


def _plan(encoder: str, pixel_format: str) -> EncodingPlan:
    return EncodingPlan(
        codec=OutputCodec.H265, encoder=encoder, encoder_args=(),
        target_transfer=HdrTransfer.HLG, tone_map_to_sdr=False, pixel_format=pixel_format,
        container="mp4",
    )  # fmt: skip


def test_hdr_frames_cross_the_pipe_in_the_layout_the_encoder_reads(monkeypatch, tmp_path):
    seen: list[list[str]] = []

    def fake_popen(cmd, **_kwargs):  # noqa: ANN001
        seen.append(list(cmd))
        raise RuntimeError("stop")

    # WHY: the real FFmpeg process is the boundary; only its command line matters here.
    monkeypatch.setattr(
        "immich_memories.processing.streaming_assembler.subprocess.Popen", fake_popen
    )
    hardware = _plan("hevc_nvenc", "p010le")
    with pytest.raises(RuntimeError, match="stop"):
        StreamingEncoder(tmp_path / "o.mp4", 64, 64, 30, encoding_plan=hardware).start()

    assert seen[0][seen[0].index("-pix_fmt") + 1] == "p010le"
    assert hdr_pipe_format(_plan("libx265", "yuv420p10le")) == "yuv420p10le"


class _Sink:
    def __init__(self) -> None:
        self.frames: list[np.ndarray] = []

    def write_frame(self, frame: np.ndarray) -> None:
        self.frames.append(frame.copy())


def test_a_p010_crossfade_into_a_missing_clip_fades_to_neutral_black():
    width, height = 4, 4
    grey = np.full(width * height * 3 // 2, 512 << 6, dtype=np.uint16)
    sink = _Sink()
    blender = FrameBlender(sink, width, height, is_hdr=True, semi_planar=True)

    blender.emit_crossfade(iter([grey, grey]), iter([]), 2)

    chroma = sink.frames[-1][width * height :]
    assert set(chroma.tolist()) == {512 << 6}


def test_a_p010_preview_shows_the_same_picture_as_planar():
    width, height = 8, 4
    rng = np.random.default_rng(1)
    y = rng.integers(64, 940, width * height, dtype=np.uint16)
    u = rng.integers(64, 960, width * height // 4, dtype=np.uint16)
    v = rng.integers(64, 960, width * height // 4, dtype=np.uint16)
    planar = np.concatenate((y, u, v))
    p010 = np.concatenate((y, np.stack((u, v), axis=1).ravel())) << 6
    previews: list[bytes] = []

    maybe_emit_preview(planar, 0.0, previews.append, True, height, width)
    maybe_emit_preview(p010, 0.0, previews.append, True, height, width, semi_planar=True)

    first, second = (np.asarray(Image.open(io.BytesIO(jpeg))) for jpeg in previews)
    assert np.array_equal(first, second)
