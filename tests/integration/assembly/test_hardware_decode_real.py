"""The assembly decodes clips on the hardware when `gpu_decode` allows it (#2709).

A 7 s 1080x1920 60 fps HEVC Main10 clip cost 3.6 s of CPU to decode in software.
Hardware decoders hand back NV12 or P010, which a format filter repacks into the
software decoder's own frames, so every filter after it sees the same pixels. A
hardware decode that fails is decoded again in software.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

from immich_memories.processing import gpu_frame_graph, streaming_frame_decoder
from immich_memories.processing.ffmpeg_runner import AssemblyContext
from immich_memories.processing.gpu_frame_graph import hardware_decode_for
from immich_memories.processing.hardware import (
    HWAccelBackend,
    HWAccelCapabilities,
    detect_hardware_acceleration,
    get_ffmpeg_hwaccel_args,
)
from immich_memories.processing.hdr_utilities import get_colorspace_filter
from immich_memories.processing.probe_cache import ProbeCache
from immich_memories.processing.streaming_assembler import streaming_assemble_full
from immich_memories.processing.streaming_frame_decoder import FrameDecoder, HardwareDecodeFailed
from tests.integration.conftest import requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]

WIDTH, HEIGHT = 320, 568


@dataclass
class _Clip:
    path: Path
    duration: float
    is_title_screen: bool = False
    rotation_override: int | None = None
    input_seek: float = 0.0


def _source(path: Path, codec: str, pix_fmt: str) -> Path:
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "testsrc2=size=568x320:rate=30:duration=2",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
            "-c:v", codec, "-pix_fmt", pix_fmt, "-c:a", "aac", "-shortest",
            # Stored landscape and turned upright on playback, the way a phone records.
            "-metadata:s:v:0", "rotate=90", str(path),
        ],
        check=True, capture_output=True,
    )  # fmt: skip
    return path


def _planes(frame: bytes) -> dict[str, np.ndarray]:
    """The yuv420p10le planes of one decoded canvas frame."""
    samples = np.frombuffer(frame, dtype="<u2").astype(np.int32)
    luma, chroma = WIDTH * HEIGHT, WIDTH * HEIGHT // 4
    return {
        "Y": samples[:luma],
        "U": samples[luma : luma + chroma],
        "V": samples[luma + chroma : luma + 2 * chroma],
    }


def _decoded_frame_info(source: Path, hwaccel_args: tuple[str, ...]) -> str:
    """FFmpeg's own description of the first decoded frame: format, range, matrix."""
    try:
        shown = subprocess.run(
            # The whole clip, the way the decoder reads it: VideoToolbox on a
            # virtual Mac has hung when FFmpeg stopped it after one frame.
            ["ffmpeg", "-nostdin", "-hide_banner", *hwaccel_args, "-i", str(source),
             "-vf", "showinfo,format=yuv420p", "-f", "null", "-"],
            capture_output=True, text=True, check=False, timeout=60,
            stdin=subprocess.DEVNULL,
        )  # fmt: skip
    except subprocess.TimeoutExpired:
        return "showinfo decode did not finish in 60 s"
    described = [
        line.split("] ", 1)[-1].strip()
        for line in shown.stderr.splitlines()
        if "Parsed_showinfo" in line and ("fmt:" in line or "color_range" in line)
    ]
    return " | ".join(described[:2])


def _frame_difference(source, hardware_decode, hardware_frames, software_frames) -> str:
    """Where and how much the hardware frames differ from the software ones."""
    lines = [f"frames: hardware {len(hardware_frames)}, software {len(software_frames)}"]
    pairs = list(zip(hardware_frames, software_frames, strict=False))
    differing = [index for index, (hw, sw) in enumerate(pairs) if hw != sw]
    lines.append(f"differing frames: {len(differing)}/{len(pairs)}, first {differing[:1]}")
    for plane in ("Y", "U", "V"):
        diffs = [
            _planes(hw)[plane] - _planes(sw)[plane]
            for hw, sw in pairs
            if len(hw) == len(sw) == WIDTH * HEIGHT * 3
        ]
        if not diffs:
            continue
        stacked = np.concatenate(diffs)
        lines.append(
            f"{plane}: max |diff| {int(np.abs(stacked).max())}, mean diff {stacked.mean():+.3f}, "
            f"mean |diff| {np.abs(stacked).mean():.3f}, "
            f"differing {100 * np.count_nonzero(stacked) / stacked.size:.2f}% (10-bit codes)"
        )
    lines.append(f"hardware args: {hardware_decode}")
    lines.append(f"hardware frame: {_decoded_frame_info(source, hardware_decode[0])}")
    lines.append(f"software frame: {_decoded_frame_info(source, ())}")
    return "\n".join(lines)


def _decoder(path: Path, hardware_decode) -> FrameDecoder:
    return FrameDecoder(
        path, WIDTH, HEIGHT, 30, pix_fmt="yuv420p10le", hardware_decode=hardware_decode
    )


@pytest.mark.parametrize(("codec", "pix_fmt"), [("libx265", "yuv420p10le"), ("libx264", "yuv420p")])
def test_hardware_decoded_frames_are_the_software_ones(tmp_path, codec, pix_fmt):
    """Hardware decoding is used only where its frames are the software decoder's.

    Where this machine's decoder strays (VideoToolbox on a virtual Mac shifts
    H.264 chroma), the gate falls back to software, and the frames prove it right.
    """
    capabilities = detect_hardware_acceleration()
    source = _source(tmp_path / f"source-{codec}.mp4", codec, pix_fmt)
    hardware_args = _hardware_args(source, capabilities)
    if hardware_args is None:
        pytest.skip("no hardware decoder for this codec here")
    hardware_decode = hardware_decode_for(source, capabilities, ProbeCache())
    software_frames = [frame.tobytes() for frame in _decoder(source, None)]
    tried = hardware_decode or (hardware_args, ProbeCache().get(source).pixel_format)
    try:
        hardware_frames = [frame.tobytes() for frame in _decoder(source, tried)]
    except HardwareDecodeFailed:
        assert hardware_decode is None, "the gate handed out a hardware decoder that fails"
        return

    # A bool, not the lists: pytest's own diff of 60 half-megabyte frames runs for minutes.
    identical = hardware_frames == software_frames
    if hardware_decode is None:
        assert not identical, "the gate refused a hardware decoder that gives the software frames"
    else:
        assert identical, _frame_difference(
            source, hardware_decode, hardware_frames, software_frames
        )


def _hardware_args(source: Path, capabilities) -> tuple[str, ...] | None:
    """The hwaccel arguments this machine has for the clip's codec, before any check."""
    codec = {"h264": "h264", "hevc": "h265"}[ProbeCache().get(source).codec]
    supported = (
        capabilities.supports_h264_decode if codec == "h264" else capabilities.supports_h265_decode
    )
    args = get_ffmpeg_hwaccel_args(
        capabilities, operation="decode", codec=codec, for_software_filters=True
    )
    return tuple(args) if supported and args else None


def test_a_failed_hardware_decode_raises_for_a_software_retry(tmp_path):
    source = _source(tmp_path / "source.mp4", "libx264", "yuv420p")
    decoder = _decoder(source, (("-hwaccel", "no-such-hwaccel"), "yuv420p"))

    with pytest.raises(HardwareDecodeFailed):
        list(decoder)


def test_the_assembly_decodes_in_software_when_the_hardware_fails(tmp_path, monkeypatch):
    source = _source(tmp_path / "source.mp4", "libx264", "yuv420p")
    clips = [_Clip(source, 2.0), _Clip(source, 2.0)]
    context = AssemblyContext(
        target_w=WIDTH,
        target_h=HEIGHT,
        pix_fmt="yuv420p",
        hdr_type="sdr",
        clip_hdr_types=[None, None],
        clip_primaries=[None, None],
        colorspace_filter=get_colorspace_filter("sdr"),
        decode_capabilities=HWAccelCapabilities(
            backend=HWAccelBackend.APPLE, supports_h264_decode=True, supports_h265_decode=True
        ),
    )
    started: list[str] = []
    real_popen = subprocess.Popen

    def recording_popen(cmd, *args, **kwargs):
        started.append(" ".join(map(str, cmd)))
        return real_popen(cmd, *args, **kwargs)

    # WHY: a hardware decoder that passed its check but cannot open these clips, so every
    # hardware decode fails.
    monkeypatch.setattr(
        streaming_frame_decoder,
        "hardware_decode_for",
        lambda _path, capabilities, _probes: (
            (("-hwaccel", "no-such-hwaccel"), "yuv420p") if capabilities else None
        ),
    )
    # WHY: the GPU filter graph has its own hwaccel arguments; this test is about the other path.
    monkeypatch.setattr(gpu_frame_graph, "gpu_filters_work", lambda _backend: False)
    # WHY: a spy on the process boundary, to count the decoders that ran.
    monkeypatch.setattr(streaming_frame_decoder.subprocess, "Popen", recording_popen)

    film = streaming_assemble_full(
        clips, ["fade"], tmp_path / "film.mp4", WIDTH, HEIGHT, 30, ctx=context
    )

    decoders = [command for command in started if "pipe:1" in command]
    assert any("no-such-hwaccel" in command for command in decoders)
    software = [command for command in decoders if "-hwaccel" not in command]
    assert len(software) == len(clips)
    frames = subprocess.run(
        ["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
         "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(film)],
        check=True, capture_output=True, text=True,
    )  # fmt: skip
    assert int(frames.stdout.strip()) == 2 * 60 - 15
