"""Transfer conversions run on the GPU where libplacebo gives zscale's picture, else zscale.

A clip's tone map (HDR to SDR), its SDR-to-HLG/PQ conversion and HLG/PQ swaps
are zscale's on the CPU. Where FFmpeg runs libplacebo on a GPU and a one-frame
probe lands within a code value of zscale, the decoder runs the same maths as a
user shader instead. Whatever fails the probe keeps zscale.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from immich_memories.processing import gpu_transfer, hdr_utilities
from immich_memories.processing.gpu_transfer import (
    TransferConversion,
    gpu_conversion_filter,
    signal_peak,
)
from immich_memories.processing.hdr_utilities import get_colorspace_filter
from immich_memories.processing.streaming_frame_decoder import make_decoder

SAMPLES = Path(__file__).parent / "fixtures" / "hdr_samples"
PHONE_CLIP = SAMPLES / "dolby_vision_84.mov"


@pytest.fixture(autouse=True)
def zscale(monkeypatch):
    # WHY: replaces the `ffmpeg -filters` run that checks the host build for zscale.
    monkeypatch.setattr(hdr_utilities, "check_zscale_available", lambda: True)


@pytest.fixture
def gpu_transfer_probe(monkeypatch):
    """Whether libplacebo matched zscale on this machine, set per test."""

    def answer(works: bool) -> None:
        # WHY: replaces the FFmpeg run that compares one frame of each chain.
        monkeypatch.setattr(gpu_transfer, "gpu_transfer_works", lambda: works)

    return answer


def _decoder(target: str, source: str | None, primaries: str = "bt2020", pipe="yuv420p10le"):
    ctx = SimpleNamespace(
        hdr_type=target,
        pix_fmt=pipe if target != "sdr" else "yuv420p",
        clip_hdr_types=[source],
        clip_primaries=[primaries],
        colorspace_filter=get_colorspace_filter(target),
    )
    clip = SimpleNamespace(path=PHONE_CLIP, duration=1.0, is_title_screen=False)
    hdr = None if target == "sdr" else target
    return make_decoder(
        clip, 0, 1080, 1920, 30, ctx, hdr_type=hdr, planar_sdr=True, hdr_pipe_format=pipe
    )


def test_an_hdr_clip_is_tone_mapped_on_the_gpu_when_the_probe_matched(gpu_transfer_probe):
    gpu_transfer_probe(True)

    graph = _decoder("sdr", "hlg")._build_vf()

    assert "libplacebo=custom_shader_path=" in graph
    assert "tonemap=" not in graph
    assert "zscale" not in graph


def test_the_tone_map_stays_on_zscale_when_the_probe_did_not_match(gpu_transfer_probe):
    gpu_transfer_probe(False)

    graph = _decoder("sdr", "hlg")._build_vf()

    assert "tonemap=tonemap=hable" in graph
    assert "libplacebo" not in graph


def test_an_sdr_clip_reaches_an_hlg_film_through_the_gpu_in_the_pipes_layout(gpu_transfer_probe):
    gpu_transfer_probe(True)

    graph = _decoder("hlg", None, primaries="bt709", pipe="p010le")._build_vf()

    assert ":format=p010le," in graph
    assert "color_trc=arib-std-b67" in graph
    assert "zscale" not in graph


def test_a_clip_already_in_the_films_transfer_gets_no_conversion(gpu_transfer_probe):
    gpu_transfer_probe(True)

    graph = _decoder("hlg", "hlg")._build_vf()

    assert "libplacebo" not in graph


def test_unknown_primaries_keep_zscale(gpu_transfer_probe):
    gpu_transfer_probe(True)

    assert gpu_conversion_filter(TransferConversion("sdr", "hlg", "film"), "yuv420p10le") == ""


@pytest.mark.parametrize(
    ("name", "peak"),
    [
        # Mastering display at 4000 nits, no content light level.
        ("hdr_vivid_sample.hevc", 40.0),
        # Content light level 1000 nits wins over the mastering display.
        ("hdr10plus_sample.hevc", 10.0),
        # No light metadata: the tonemap filter's 1000-nit default.
        ("dolby_vision_84.mov", 10.0),
    ],
)
def test_the_tone_map_peak_is_the_one_the_tonemap_filter_reads(name, peak):
    assert signal_peak(SAMPLES / name) == peak


def test_the_shader_tone_maps_with_the_clips_own_peak():
    bright = TransferConversion("pq", "sdr", peak=40.0).shader()
    default = TransferConversion("pq", "sdr").shader()

    assert bright != default
    assert "hable(sig)" in bright


def _probe_output(conversion: TransferConversion, gpu_chroma_offset: int) -> bytes:
    """One stacked frame as the probe reads it: zscale's rows, then the GPU's."""
    ten_bit = conversion.target != "sdr"
    dtype = np.uint16 if ten_bit else np.uint8
    luma = np.full((144, 256), 400 if ten_bit else 100, dtype)
    chroma = np.full((72, 128), 512 if ten_bit else 128, dtype)
    planes = [np.vstack([luma, luma]), np.vstack([chroma, chroma + gpu_chroma_offset])]
    planes.append(planes[1])
    return b"".join(plane.tobytes() for plane in planes)


@pytest.mark.parametrize(("offset", "matched"), [(0, True), (40, False)])
def test_the_probe_only_passes_a_gpu_picture_within_a_code_value(monkeypatch, offset, matched):
    conversion = TransferConversion("hlg", "sdr")
    output = _probe_output(conversion, offset)

    def ffmpeg(command, **_kwargs):
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr=b"")

    # WHY: replaces the FFmpeg run; the stacked frame stands for its output.
    monkeypatch.setattr(gpu_transfer.subprocess, "run", ffmpeg)

    assert gpu_transfer._probe_case(conversion, "null", "null") is matched


def test_the_probe_fails_where_ffmpeg_cannot_run_libplacebo(monkeypatch):
    def ffmpeg(command, **_kwargs):
        return subprocess.CompletedProcess(command, 1, stdout=b"", stderr=b"No such filter")

    # WHY: replaces the FFmpeg run, which fails on a build without libplacebo.
    monkeypatch.setattr(gpu_transfer.subprocess, "run", ffmpeg)

    assert gpu_transfer._probe_case(TransferConversion("hlg", "sdr"), "null", "null") is False
