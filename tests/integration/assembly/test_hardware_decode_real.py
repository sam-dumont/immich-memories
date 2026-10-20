"""The assembly decodes clips on the hardware when `gpu_decode` allows it (#2709).

A 7 s 1080x1920 60 fps HEVC Main10 clip cost 3.6 s of CPU to decode in software.
Hardware decoders hand back NV12 or P010, which a format filter repacks into the
software decoder's own frames, so every filter after it sees the same pixels. A
hardware decode that fails is decoded again in software.
"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from immich_memories.processing import gpu_frame_graph, hardware, streaming_frame_decoder
from immich_memories.processing.ffmpeg_runner import AssemblyContext
from immich_memories.processing.hardware import (
    HWAccelBackend,
    HWAccelCapabilities,
    detect_hardware_acceleration,
)
from immich_memories.processing.hdr_utilities import get_colorspace_filter
from immich_memories.processing.probe_cache import ProbeCache
from immich_memories.processing.streaming_assembler import streaming_assemble_full
from immich_memories.processing.streaming_frame_decoder import (
    FrameDecoder,
    HardwareDecodeFailed,
    hardware_decode_for,
)
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


def _hashes(decoder: FrameDecoder) -> list[str]:
    return [hashlib.sha256(frame.tobytes()).hexdigest() for frame in decoder]


def _decoder(path: Path, hardware_decode) -> FrameDecoder:
    return FrameDecoder(
        path, WIDTH, HEIGHT, 30, pix_fmt="yuv420p10le", hardware_decode=hardware_decode
    )


@pytest.mark.parametrize(("codec", "pix_fmt"), [("libx265", "yuv420p10le"), ("libx264", "yuv420p")])
def test_hardware_decoded_frames_are_the_software_ones(tmp_path, codec, pix_fmt):
    capabilities = detect_hardware_acceleration()
    source = _source(tmp_path / f"source-{codec}.mp4", codec, pix_fmt)
    hardware_decode = hardware_decode_for(source, capabilities, ProbeCache())
    if hardware_decode is None:
        pytest.skip("no hardware decoder for this codec here")

    assert _hashes(_decoder(source, hardware_decode)) == _hashes(_decoder(source, None))


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

    # WHY: a hardware decoder this FFmpeg cannot open, so every hardware decode fails.
    monkeypatch.setattr(
        hardware, "get_ffmpeg_hwaccel_args", lambda *_a, **_k: ["-hwaccel", "no-such-hwaccel"]
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
