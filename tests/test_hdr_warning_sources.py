"""The HDR tone-mapping warning names a real HDR source, not the app's own photo intermediates (#2213)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from immich_memories.config_loader import Config
from immich_memories.generate import GenerationParams
from immich_memories.generate_settings import build_assembly_settings
from immich_memories.processing.assembly_config import AssemblyClip
from immich_memories.processing.encoding_plan import HdrMode


def _clip(tmp_path: Path, name: str, **fields) -> AssemblyClip:
    path = tmp_path / f"{name}.mp4"
    path.write_bytes(b"\x00" * 64)
    return AssemblyClip(path=path, duration=3.0, asset_id=name, **fields)


def _settings(tmp_path, clips, caplog, hdr_type="pq"):
    config = Config()
    config.hardware.enabled = False
    config.output.codec = "h264"
    config.output.hdr_mode = HdrMode.AUTO
    params = GenerationParams(clips=[], output_path=tmp_path / "m.mp4", config=config)
    with (
        # WHY: ffprobe is the external boundary; the tag it would report is the input.
        patch("immich_memories.processing.hdr_utilities._detect_hdr_type", return_value=hdr_type),
        caplog.at_level("WARNING"),
    ):
        return build_assembly_settings(params, clips)


def test_a_photo_only_library_does_not_warn_about_hdr(tmp_path, caplog: pytest.LogCaptureFixture):
    # The photo renderer encodes every still as a PQ intermediate, so the probe sees HDR.
    clips = [_clip(tmp_path, f"jpeg-{n}", is_photo=True) for n in range(3)]

    settings = _settings(tmp_path, clips, caplog)

    assert settings.encoding_plan.tone_map_to_sdr is True
    assert "HDR input was detected" not in caplog.text


def test_an_hdr_video_among_photos_warns_and_names_it(tmp_path, caplog: pytest.LogCaptureFixture):
    clips = [_clip(tmp_path, "still", is_photo=True), _clip(tmp_path, "iphone-video")]

    _settings(tmp_path, clips, caplog)

    assert "HDR input was detected" in caplog.text
    assert "iphone-video" in caplog.text
    assert "still" not in caplog.text.replace("HDR input was detected", "")


def test_a_gain_mapped_photo_counts_as_an_hdr_source(tmp_path, caplog: pytest.LogCaptureFixture):
    clips = [_clip(tmp_path, "heic-hdr", is_photo=True, gain_map_hdr=True)]

    _settings(tmp_path, clips, caplog)

    assert "heic-hdr" in caplog.text
