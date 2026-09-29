"""An Apple gain-mapped HEIC becomes the same HDR pixels without full-size float copies (#1527)."""

from __future__ import annotations

import struct
import tracemalloc

import cv2
import numpy as np
import pytest
from PIL import Image

from immich_memories.photos import animator

pillow_heif = pytest.importorskip("pillow_heif")

_GAIN_KEY = "urn:com:apple:photo:2020:aux:hdrgainmap"


def _makernote() -> bytes:
    # HDRHeadroom 1.01 and HDRGain 0.00608: Apple's pair for a 5.956x headroom.
    header = b"Apple iOS\x00\x00\x01MM" + struct.pack(">H", 2)
    entries = struct.pack(">HHII", 0x0021, 10, 1, 40) + struct.pack(">HHII", 0x0030, 10, 1, 48)
    return header + entries + struct.pack(">iiii", 101, 100, 608, 100000)


def _photo(tmp_path, width: int, height: int):
    x = np.linspace(0, 255, width, dtype=np.float32)[None, :]
    y = np.linspace(0, 255, height, dtype=np.float32)[:, None]
    pixels = np.stack([x + 0 * y, y + 0 * x, (x + y) / 2], axis=-1).astype(np.uint8)
    exif = Image.Exif()
    exif.get_ifd(0x8769)[0x927C] = _makernote()
    pillow_heif.register_heif_opener()
    path = tmp_path / "IMG_0001.HEIC"
    Image.fromarray(pixels).save(path, format="HEIF", quality=95, exif=exif.tobytes())
    gain = ((np.arange(width // 4)[None, :] + np.arange(height // 4)[:, None]) * 7 % 256).astype(
        np.uint8
    )
    return path, Image.fromarray(gain, "L")


@pytest.fixture
def gain_mapped(tmp_path, monkeypatch):
    def make(width: int, height: int):
        path, gain = _photo(tmp_path, width, height)

        class Aux:
            def to_pillow(self):
                return gain.copy()

        class Primary:
            info = {"aux": {_GAIN_KEY: [7]}}

            def get_aux_image(self, _item):
                return Aux()

        # WHY: pillow-heif cannot write an auxiliary gain-map image, so reading one
        # is the single stand-in; the primary picture and its EXIF are a real HEIC.
        monkeypatch.setattr(pillow_heif, "open_heif", lambda *_args, **_kwargs: [Primary()])
        return path, gain

    return make


def _expected(path, gain_map: Image.Image, headroom: float) -> np.ndarray:
    with Image.open(path) as opened:
        sdr = np.asarray(opened.convert("RGB"), dtype=np.float64) / 255.0
    gain = np.asarray(gain_map.resize(sdr.shape[1::-1], Image.Resampling.LANCZOS), dtype=np.float64)
    gain = gain / 255.0

    def eotf(v):
        return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)

    linear = eotf(sdr) * (1.0 + (headroom - 1.0) * eotf(gain))[:, :, None]
    return np.clip(linear / headroom, 0, 1) * 65535


def test_the_gain_map_is_applied_in_linear_light_to_every_pixel(tmp_path, gain_mapped):
    path, gain = gain_mapped(96, 64)
    prepared = animator.prepare_photo_source(path, tmp_path)

    assert prepared.has_gain_map
    assert prepared.peak_nits == int(animator._headroom_from_stops(1.01, 0.00608) * 203)
    written = cv2.cvtColor(cv2.imread(str(prepared.path), cv2.IMREAD_UNCHANGED), cv2.COLOR_BGR2RGB)
    assert written.dtype == np.uint16
    expected = _expected(path, gain, prepared.peak_nits / 203)
    assert np.abs(written.astype(np.float64) - expected).max() <= 70


def test_applying_a_gain_map_holds_no_full_size_float_copies(tmp_path, gain_mapped):
    width, height = 1200, 900
    path, _gain = gain_mapped(width, height)
    tracemalloc.start()
    try:
        animator.prepare_photo_source(path, tmp_path)
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    # The 16-bit result is 6 bytes a pixel. A float32 RGB copy is 12 on its own;
    # the whole-image maths used to hold several at once (about 75 bytes a pixel).
    assert peak < width * height * 16
