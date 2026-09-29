"""A photo clip's frames reach the encoder without extra full-frame copies (#1527)."""

from __future__ import annotations

import tracemalloc
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from immich_memories.api.models import AssetType
from immich_memories.config_models_render import PhotoConfig
from immich_memories.photos import photo_pipeline
from immich_memories.processing import hdr_utilities
from tests.conftest import make_asset

WIDTH, HEIGHT = 540, 960


@pytest.fixture
def encoder(monkeypatch):
    """Pull frames the way the ffmpeg pipe does, noting what each one costs to make."""
    seen: dict[str, list] = {"growth": [], "frames": []}

    def pipe(cmd, frames, **_kwargs):
        pulled = iter(frames)
        seen["frames"].append(bytes(next(pulled)))  # the first frame also scales the source
        while True:
            held = tracemalloc.get_traced_memory()[0]
            tracemalloc.reset_peak()
            try:
                frame = next(pulled)
            except StopIteration:
                break
            seen["growth"].append(tracemalloc.get_traced_memory()[1] - held)
            seen["frames"].append(bytes(frame))
            del frame
        Path(cmd[-1]).write_bytes(b"\0" * 200)
        return 0, ""

    # WHY: the ffmpeg process is the write boundary; the test reads what is written to it.
    monkeypatch.setattr(photo_pipeline, "write_frames_to_ffmpeg", pipe)
    return seen


@pytest.mark.parametrize("sixteen_bit", [True, False])
def test_each_frame_costs_about_one_float_frame_not_four(
    tmp_path, monkeypatch, encoder, sixteen_bit
):
    # WHY: whether this machine's ffmpeg has zscale decides the pipe format;
    # the test chooses it so both the 16-bit and the 8-bit pipe are covered.
    monkeypatch.setattr(hdr_utilities, "check_zscale_available", lambda: True)
    source = tmp_path / "IMG_0001.jpg"
    pixels = np.random.default_rng(0).integers(0, 255, (900, 1200, 3), dtype=np.uint8)
    Image.fromarray(pixels).save(source, quality=90)
    asset = make_asset("photo-1", original_file_name=source.name).model_copy(
        update={"type": AssetType.IMAGE}
    )
    if sixteen_bit:
        monkeypatch.setattr(
            photo_pipeline,
            "_prepared_photo_pixels",
            _as_gain_mapped(photo_pipeline._prepared_photo_pixels),
        )

    tracemalloc.start()
    try:
        clip = photo_pipeline.render_single_photo(
            asset,
            PhotoConfig(duration=1.0),
            WIDTH,
            HEIGHT,
            tmp_path,
            None,
            source_path=source,
        )
    finally:
        tracemalloc.stop()

    assert clip is not None
    frame_bytes = WIDTH * HEIGHT * (6 if sixteen_bit else 3)
    assert all(len(frame) == frame_bytes for frame in encoder["frames"])
    # The float32 viewport frame alone is 12 bytes a pixel; converting it used to
    # hold a scaled copy, a clipped copy and the integer frame twice on top.
    assert max(encoder["growth"]) < WIDTH * HEIGHT * 12


def _as_gain_mapped(prepare):
    def wrapped(*args):
        prepared, img = prepare(*args)
        prepared.has_gain_map = True
        return prepared, img

    return wrapped
