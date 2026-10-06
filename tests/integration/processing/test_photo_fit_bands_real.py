"""A still rendered with `scale_mode: fit` has black bands in the encoded clip (#2132).

The photo renderer filled every band with the picture's own blur whatever the scale mode, so a
`fit` film still showed blurred bands around each portrait still. This encodes a real clip with
FFmpeg and reads its pixels back.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from immich_memories.config_models_render import PhotoConfig
from immich_memories.photos.photo_pipeline import render_single_photo
from tests.conftest import make_clip
from tests.integration.conftest import requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]

CANVAS_W, CANVAS_H = 640, 360


def _portrait(path: Path) -> Path:
    rng = np.random.default_rng(7)
    pixels = rng.integers(120, 230, size=(480, 360, 3), dtype=np.uint8)
    Image.fromarray(pixels).save(path, quality=95)
    return path


def _middle_frame(clip: Path) -> np.ndarray:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", "1.0", "-i", str(clip), "-frames:v", "1"]
        + ["-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True,
        check=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.uint8).reshape(CANVAS_H, CANVAS_W)


def _render(tmp_path: Path, scale_mode: str) -> np.ndarray:
    work = tmp_path / scale_mode
    work.mkdir()
    asset = make_clip(f"portrait-{scale_mode}").asset
    clip = render_single_photo(
        asset=asset,
        config=PhotoConfig(duration=2.0),
        target_w=CANVAS_W,
        target_h=CANVAS_H,
        work_dir=work,
        download_fn=None,
        source_path=_portrait(work / "portrait.jpg"),
        scale_mode=scale_mode,
    )
    assert clip is not None
    return _middle_frame(clip.path)


def test_a_fitted_portrait_still_sits_between_black_bands(tmp_path):
    luma = _render(tmp_path, "fit")

    # Video range black is code 16; a blurred band of this picture sits near 170.
    assert luma[:, :40].mean() < 24
    assert luma[:, -40:].mean() < 24
    assert luma[:, CANVAS_W // 2].mean() > 100


def test_a_blurred_portrait_still_fills_its_bands(tmp_path):
    luma = _render(tmp_path, "blur")

    assert luma[:, :40].mean() > 100
