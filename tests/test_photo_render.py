"""A photo clip preserves HDR only when its source and the film need it."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from immich_memories.config_loader import Config
from immich_memories.config_models_render import PhotoConfig
from immich_memories.generate import GenerationParams
from immich_memories.generate_photos import render_photo_as_clip
from immich_memories.photos.photo_pipeline import render_single_photo
from immich_memories.processing.hardware import HWAccelBackend, HWAccelCapabilities
from tests.conftest import make_asset, make_clip
from tests.test_photo_format_dispatch import _rotated_ultrahdr_jpeg

CONFIG = PhotoConfig(duration=1.0)


def _sdr_photo(tmp_path: Path) -> Path:
    path = tmp_path / "photo.jpg"
    Image.new("RGB", (96, 64), "orange").save(path, "JPEG")
    return path


def _gain_mapped_photo(tmp_path: Path) -> Path:
    path = tmp_path / "hdr.jpg"
    _rotated_ultrahdr_jpeg(path)
    return path


def _render(tmp_path: Path, source: Path, frame_size=(96, 64)):
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    download = MagicMock()  # WHY: the source is local, so Immich must never be asked
    clip = render_single_photo(
        make_asset("photo-1"), CONFIG, *frame_size, work, download, fps=5, source_path=source
    )
    download.assert_not_called()
    return clip


class _FFmpeg:
    """WHY: FFmpeg is the boundary; this records the command and answers like it."""

    def __init__(self, returncode: int = 0, stderr: str = "") -> None:
        self.command: list[str] = []
        self.returncode = returncode
        self.stderr = stderr

    def __call__(self, command, frames, **_):
        self.command = command
        for _frame in frames:
            pass
        if self.returncode == 0:
            Path(command[-1]).write_bytes(b"\0" * 200)
        return self.returncode, self.stderr


def _command(
    tmp_path, source, *, zscale: bool, encoders: str = "libx265", frame_size=(96, 64)
) -> list[str]:
    ffmpeg = _FFmpeg()
    capabilities = HWAccelCapabilities()
    if "hevc_videotoolbox" in encoders:
        capabilities = HWAccelCapabilities(backend=HWAccelBackend.APPLE, supports_h265_encode=True)
    # WHY: three FFmpeg boundaries: the encode, and the two capability probes
    with (
        # WHY: the encode itself; the command is what is under test
        patch("immich_memories.photos.photo_pipeline.write_frames_to_ffmpeg", ffmpeg),
        # WHY: which filters the installed FFmpeg has decides the route
        patch("immich_memories.processing.hdr_utilities.check_zscale_available", lambda: zscale),
        # WHY: the real hardware probe decides which encoder can actually run.
        patch(
            "immich_memories.processing.hardware.detect_hardware_acceleration",
            return_value=capabilities,
        ),
    ):
        clip = _render(tmp_path, source, frame_size)
    assert clip is not None
    assert clip.is_photo
    assert clip.duration == CONFIG.duration
    return ffmpeg.command


def test_a_plain_photo_uses_sdr_h264_even_with_zscale(tmp_path):
    command = _command(tmp_path, _sdr_photo(tmp_path), zscale=True)

    assert command[command.index("-pix_fmt") + 1] == "rgb24"
    assert "zscale=t=smpte2084:tin=iec61966-2-1" in command[command.index("-vf") + 1]
    assert command[command.index("-color_trc") + 1] == "bt709"
    assert command[command.index("-c:v") + 1] == "libx264"


def test_a_gain_mapped_photo_is_piped_16_bit_linear(tmp_path):
    command = _command(tmp_path, _gain_mapped_photo(tmp_path), zscale=True)

    assert command[command.index("-pix_fmt") + 1] == "rgb48le"
    assert "tin=linear" in command[command.index("-vf") + 1]


def test_photo_preparation_uses_verified_nvidia_hardware(tmp_path):
    ffmpeg = _FFmpeg()
    capabilities = HWAccelCapabilities(backend=HWAccelBackend.NVIDIA, supports_h265_encode=True)
    with (
        # WHY: capture the actual encoder command at the subprocess boundary.
        patch("immich_memories.photos.photo_pipeline.write_frames_to_ffmpeg", ffmpeg),
        # WHY: the installed FFmpeg filter capability determines color conversion.
        patch("immich_memories.processing.hdr_utilities.check_zscale_available", lambda: True),
        # WHY: model the real encoder probe result on an NVIDIA host.
        patch(
            "immich_memories.processing.hardware.detect_hardware_acceleration",
            return_value=capabilities,
        ),
    ):
        clip = _render(tmp_path, _gain_mapped_photo(tmp_path))
    assert clip is not None
    assert ffmpeg.command[ffmpeg.command.index("-c:v") + 1] == "hevc_nvenc"
    assert ffmpeg.command[ffmpeg.command.index("-color_trc") + 1] == "smpte2084"


def test_nas_photo_uses_hardware_h264_with_real_tone_mapping(tmp_path):
    ffmpeg = _FFmpeg()
    capabilities = HWAccelCapabilities(backend=HWAccelBackend.VAAPI, supports_h264_encode=True)
    params = GenerationParams(
        clips=[],
        output_path=tmp_path / "film.mp4",
        config=Config(tier="basic", photos={"duration": 1}),
        output_resolution="720p",
    )
    with (
        # WHY: inspect the emitted FFmpeg command without requiring a local VAAPI device.
        patch("immich_memories.photos.photo_pipeline.write_frames_to_ffmpeg", ffmpeg),
        # WHY: the installed FFmpeg color-conversion capability is external.
        patch("immich_memories.processing.hdr_utilities.check_zscale_available", lambda: True),
        # WHY: this is the capability actually measured on the NAS.
        patch(
            "immich_memories.processing.hardware.detect_hardware_acceleration",
            return_value=capabilities,
        ),
    ):
        clip = render_photo_as_clip(
            make_clip("photo"), params, tmp_path, source_path=_gain_mapped_photo(tmp_path)
        )
    assert clip is not None
    command = ffmpeg.command
    assert command[command.index("-c:v") + 1] == "h264_vaapi"
    assert "tonemap=" in command[command.index("-vf") + 1]
    assert "hwupload" in command[command.index("-vf") + 1]
    assert command[command.index("-color_trc") + 1] == "bt709"


@pytest.mark.parametrize("source", [_sdr_photo, _gain_mapped_photo])
def test_without_zscale_every_photo_is_plain_sdr_h264(tmp_path, source):
    """Tagging unconverted pixels as HDR would be worse than an honest SDR clip."""
    command = _command(tmp_path, source(tmp_path), zscale=False)

    assert command[command.index("-pix_fmt") + 1] == "rgb24"
    assert command[command.index("-vf") + 1] == "format=yuv420p"
    assert command[command.index("-c:v") + 1] == "libx264"
    assert not any("zscale" in part or "bt2020" in part for part in command[:-1])


@pytest.mark.parametrize(
    ("encoders", "codec"),
    [("hevc_videotoolbox libx265", "hevc_videotoolbox"), ("libx264 libx265", "libx265")],
)
def test_the_hevc_encoder_is_the_hardware_one_when_ffmpeg_has_it(tmp_path, encoders, codec):
    command = _command(tmp_path, _gain_mapped_photo(tmp_path), zscale=True, encoders=encoders)

    assert command[command.index("-c:v") + 1] == codec


def test_a_failed_encode_raises_with_what_ffmpeg_said(tmp_path):
    # WHY: FFmpeg failing mid-encode is the case under test
    with (
        # WHY: an FFmpeg that exits non-zero with a message on stderr
        patch(
            "immich_memories.photos.photo_pipeline.write_frames_to_ffmpeg",
            _FFmpeg(returncode=1, stderr="Error: codec not found"),
        ),
        pytest.raises(RuntimeError, match="codec not found"),
    ):
        _render(tmp_path, _sdr_photo(tmp_path))


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_a_real_render_is_a_clip_of_the_configured_length(tmp_path):
    clip = _render(tmp_path, _sdr_photo(tmp_path))

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json",
         str(clip.path)],
        check=True, capture_output=True, text=True,
    )  # fmt: skip
    assert float(json.loads(probe.stdout)["format"]["duration"]) == pytest.approx(1.0, abs=0.1)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_an_ffmpeg_without_zscale_still_renders_the_photo(tmp_path):
    """Homebrew's FFmpeg ships without libzimg; the photo must come out SDR, not crash."""
    real_run = subprocess.run

    def ffmpeg_without_zscale(command, *args, **kwargs):
        if "-filters" in command:
            return subprocess.CompletedProcess(command, 0, stdout=" ... scale  V->V  Scale\n")
        return real_run(command, *args, **kwargs)

    # WHY: FFmpeg's filter list is the boundary; everything else runs for real
    with patch("immich_memories.processing.hdr_utilities.subprocess.run", ffmpeg_without_zscale):
        clip = _render(tmp_path, _sdr_photo(tmp_path))

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=codec_name,pix_fmt,color_transfer", "-of", "json", str(clip.path)],
        check=True, capture_output=True, text=True,
    )  # fmt: skip
    stream = json.loads(probe.stdout)["streams"][0]
    assert stream["codec_name"] == "h264"
    assert stream["pix_fmt"] == "yuv420p"
    assert stream.get("color_transfer") != "smpte2084"
