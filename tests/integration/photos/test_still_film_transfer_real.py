"""A still rendered in an HLG film's transfer plays without a conversion per frame (#2709).

Gain-mapped stills came out as PQ and SDR stills as SDR, and the assembly decoder
converted each of their frames to HLG with zscale: about 120 ms a frame. With the
film's transfer known, the still's move resamples in its own transfer as before and
only the picture it moves over is converted, once. These tests render the same
still both ways and compare what the film decodes.

Run: make test-integration-photos
"""

from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from immich_memories.api.models import Asset, AssetType
from immich_memories.config.loader import Config
from immich_memories.config.models.render import PhotoConfig
from immich_memories.photos.photo_pipeline import render_single_photo
from immich_memories.processing.encoding_plan import HdrTransfer
from immich_memories.processing.streaming_frame_decoder import make_decoder
from tests.conftest import HDR_SAMPLES, lfs_fixture
from tests.integration.conftest import requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]

WIDTH, HEIGHT, FPS = 640, 360, 30


def _sdr_still(path: Path) -> Path:
    rows, columns = np.mgrid[0:600, 0:800]
    picture = np.stack(
        [columns * 255 // 799, rows * 255 // 599, 128 + 100 * np.sin(columns / 40.0)], -1
    )
    picture[200:300, 300:500] = (240, 30, 30)
    Image.fromarray(picture.astype(np.uint8)).save(path, quality=95)
    return path


def _render(source: Path, work: Path, film_transfer: HdrTransfer | None):
    work.mkdir()
    asset = Asset(
        id=str(uuid.uuid5(uuid.NAMESPACE_URL, source.name)),
        type=AssetType.IMAGE,
        originalFileName=source.name,
        fileCreatedAt="2025-01-01T00:00:00Z",
        fileModifiedAt="2025-01-01T00:00:00Z",
        updatedAt="2025-01-01T00:00:00Z",
    )
    config = Config(hardware={"enabled": False}, output={"codec": "h265"})
    clip = render_single_photo(
        asset, PhotoConfig(duration=1.0), WIDTH, HEIGHT, work, None, FPS,
        source_path=source, encoding_config=config, film_transfer=film_transfer,
    )  # fmt: skip
    assert clip is not None
    decoder = make_decoder(
        SimpleNamespace(path=clip.path, duration=1.0, is_title_screen=False),
        0, WIDTH, HEIGHT, FPS, None, hdr_type="hlg",
    )  # fmt: skip
    frames = np.stack([frame.astype(np.int64) for frame in decoder])
    return clip.path, decoder._build_vf(), frames


def _transfer(path: Path) -> str:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=color_transfer", "-of", "json",
         str(path)],
        check=True, capture_output=True, text=True,
    )  # fmt: skip
    return json.loads(probe.stdout)["streams"][0]["color_transfer"]


def _luma_psnr(a: np.ndarray, b: np.ndarray) -> float:
    luma = WIDTH * HEIGHT
    mse = np.mean((a[:, :luma] - b[:, :luma]).astype(np.float64) ** 2)
    return float(10 * np.log10(1023**2 / mse))


@pytest.mark.parametrize(
    ("source", "floor_db"),
    [
        # Two lossy intermediates and the order of the conversion apart: 43.9 dB on this
        # night scene's point lights at this size (50.1 dB at 1080x1920 losslessly).
        (lambda _tmp: lfs_fixture(HDR_SAMPLES / "gain_mapped-photo-tokyo.jpg"), 42.0),
        (lambda tmp: _sdr_still(tmp / "sdr.jpg"), 45.0),
    ],
    ids=["gain-mapped", "sdr"],
)
def test_a_still_in_the_films_transfer_needs_no_conversion_per_frame(tmp_path, source, floor_db):
    still = source(tmp_path)
    old_path, old_vf, old = _render(still, tmp_path / "own", None)
    new_path, new_vf, new = _render(still, tmp_path / "film", HdrTransfer.HLG)

    assert _transfer(new_path) == "arib-std-b67"
    assert "zscale" in old_vf
    assert "zscale" not in new_vf
    assert new.shape == old.shape
    assert _luma_psnr(new, old) > floor_db
