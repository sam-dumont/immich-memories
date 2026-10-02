"""Streaming decode consumes the caller's existing source metadata."""

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from immich_memories.processing.assembly_config import AssemblyClip
from immich_memories.processing.probe_cache import ProbeCache
from immich_memories.processing.streaming_assembler import streaming_assemble_full
from tests.integration.conftest import requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]


@pytest.mark.parametrize("warm", [True, False])
@pytest.mark.parametrize("has_audio", [True, False])
def test_source_metadata_is_reused_during_assembly(tmp_path, monkeypatch, warm, has_audio):
    source = tmp_path / "source.mkv"
    audio = (
        ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=0.3"]
        if has_audio
        else []
    )
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=128x72:rate=30:duration=0.3",
            *audio,
            "-c:v",
            "ffv1",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
            "-colorspace",
            "bt709",
            "-c:a",
            "pcm_s16le",
            str(source),
        ],
        check=True,
        capture_output=True,
        timeout=20,
    )
    cache = ProbeCache()
    if warm:
        cache.get(source)
    context = SimpleNamespace(
        hdr_type="sdr",
        pix_fmt="yuv420p",
        clip_hdr_types=[None],
        clip_primaries=["bt709"],
        colorspace_filter="",
    )
    original = subprocess.run
    probes = []

    def observe(command, *args, **kwargs):
        if Path(command[0]).name == "ffprobe" and Path(command[-1]).resolve() == source.resolve():
            probes.append(command)
        return original(command, *args, **kwargs)

    # WHY: observe the process boundary while every metadata read and render
    # still runs real FFmpeg; the test never supplies a fabricated probe result.
    monkeypatch.setattr(subprocess, "run", observe)
    output = tmp_path / "output.mp4"
    streaming_assemble_full(
        [AssemblyClip(source, 0.2)] * 2,
        ["cut"],
        output,
        72,
        128,
        30,
        ctx=context if warm else None,
        probe_cache=cache if warm else None,
    )
    assert output.stat().st_size > 0
    assert len(probes) == (0 if warm else 1)
    rendered = ProbeCache().get(output)
    assert rendered.has_audio
    assert rendered.video_duration_seconds == pytest.approx(0.4, abs=0.001)
