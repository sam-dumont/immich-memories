"""NAS source preparation and assembly use bounded, correctly colored video."""

import subprocess
from pathlib import Path

import pytest

from immich_memories.config_loader import Config
from immich_memories.generate import GenerationParams
from immich_memories.generate_settings import build_assembly_settings
from immich_memories.processing.assembly_config import AssemblyClip
from immich_memories.processing.hardware import HWAccelBackend, HWAccelCapabilities
from tests.integration.conftest import ffprobe_json, requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]


@pytest.fixture(params=[("3840x2160", "smpte2084"), ("2160x3840", "arib-std-b67")])
def hdr_source(tmp_path: Path, request) -> Path:
    size, transfer = request.param
    source = tmp_path / "hdr.mp4"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color=gray:s={size}:r=30",
            "-frames:v", "3", "-pix_fmt", "yuv420p10le", "-c:v", "libx265",
            "-preset", "ultrafast", "-x265-params",
            "pools=1:frame-threads=1:rc-lookahead=0:bframes=0:repeat-headers=1:"
            f"colorprim=bt2020:transfer={transfer}:colormatrix=bt2020nc", str(source),
        ], check=True, capture_output=True,
    )  # fmt: skip
    assert ffprobe_json(source)["streams"][0]["color_transfer"] == transfer
    return source


def test_nas_automatic_hdr_uses_available_hardware(hdr_source, tmp_path, monkeypatch):
    config = Config(tier="nas", output={"codec": "h265", "hdr_mode": "auto", "resolution": "4k"})
    params = GenerationParams(clips=[], output_path=tmp_path / "film.mp4", config=config)
    # WHY: Model a NAS driver with H.264 encode but no HEVC encode on any test host.
    monkeypatch.setattr(
        "immich_memories.generate_settings.detect_hardware_acceleration",
        lambda _backend: HWAccelCapabilities(
            backend=HWAccelBackend.VAAPI, supports_h264_encode=True
        ),
    )
    settings = build_assembly_settings(params, [AssemblyClip(path=hdr_source, duration=0.1)])
    assert settings.target_resolution == (1920, 1080)
    assert settings.encoding_plan.encoder == "h264_vaapi"
    assert settings.encoding_plan.tone_map_to_sdr
    assert not settings.encoding_plan.hdr


@pytest.mark.parametrize("hardware_enabled", [True, False])
def test_nas_reencoded_clip_is_1080p_sdr(hdr_source, tmp_path, caplog, hardware_enabled):
    from immich_memories.processing.clips import extract_clip
    from immich_memories.processing.hardware import detect_hardware_acceleration

    config = Config(tier="nas", hardware={"enabled": hardware_enabled})
    with caplog.at_level("INFO"):
        output = extract_clip(
            hdr_source, 0, 0.1, tmp_path / "clip.mp4", reencode=True, config=config
        )
    stream = ffprobe_json(output)["streams"][0]
    assert sorted((stream["width"], stream["height"])) == [1080, 1920]
    assert stream["codec_name"] == "h264"
    assert stream["color_transfer"] == "bt709"
    assert stream["color_primaries"] == "bt709"
    if hardware_enabled and detect_hardware_acceleration().supports_h264_encode:
        assert "Using hardware encoder: h264_" in caplog.text
        assert "falling back to software" not in caplog.text


@pytest.mark.parametrize(
    "tier,codec_policy,hardware_enabled,hevc_hardware,encoder",
    [
        ("full", "prefer_hardware", True, False, "libx265"),
        ("gpu", "prefer_hardware", True, False, "libx265"),
        ("nas", "strict", True, False, "libx265"),
        ("nas", "prefer_hardware", False, False, "libx265"),
        ("nas", "prefer_hardware", True, True, "hevc_vaapi"),
    ],
)
def test_hdr_is_preserved_outside_the_nas_h264_policy(
    hdr_source, tmp_path, monkeypatch, tier, codec_policy, hardware_enabled, hevc_hardware, encoder
):
    config = Config(
        tier=tier,
        output={"codec": "h265", "codec_policy": codec_policy},
        hardware={"enabled": hardware_enabled},
        llm={"enabled": True, "base_url": "http://localhost:9999/v1", "model": "test-reader"},
    )
    # WHY: Exercise hardware capabilities independently of the test host's driver.
    monkeypatch.setattr(
        "immich_memories.generate_settings.detect_hardware_acceleration",
        lambda _backend: HWAccelCapabilities(
            backend=HWAccelBackend.VAAPI,
            supports_h264_encode=True,
            supports_h265_encode=hevc_hardware,
        ),
    )
    params = GenerationParams(clips=[], output_path=tmp_path / "film.mp4", config=config)
    plan = build_assembly_settings(
        params, [AssemblyClip(path=hdr_source, duration=0.1)]
    ).encoding_plan
    assert plan.encoder == encoder
    assert plan.hdr
