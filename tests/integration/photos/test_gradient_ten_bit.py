"""A gradient keeps its 10-bit PQ levels after the integer-depth render (#1527).

Both frames go through the photo clip's own zscale chain to yuv420p10le and stop
there, before the lossy encoder, whose own error is larger than anything measured
here.
"""

from __future__ import annotations

import subprocess

import numpy as np
import pytest

from immich_memories.photos.photo_pipeline import photo_filter_chain
from immich_memories.processing.hdr_utilities import check_zscale_available
from tests.integration.conftest import requires_ffmpeg
from tests.test_photo_gradient_depth import HEIGHT, WIDTH, rendered_and_reference

pytestmark = [pytest.mark.integration, requires_ffmpeg]


def _ten_bit_luma(frame: np.ndarray) -> np.ndarray:
    pix_fmt, chain = photo_filter_chain(
        gain_map_hdr=True, has_zscale=True, peak_nits=1000, primaries="bt709"
    )
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "rawvideo", "-pix_fmt", pix_fmt]
        + ["-s", f"{WIDTH}x{HEIGHT}", "-i", "-", "-vf", chain]
        + ["-f", "rawvideo", "-pix_fmt", "yuv420p10le", "-"],
        input=frame.tobytes(),
        capture_output=True,
        check=True,
    ).stdout
    return np.frombuffer(raw, np.uint16)[: WIDTH * HEIGHT].reshape(HEIGHT, WIDTH)


@pytest.mark.parametrize(("low", "high"), [(0.0, 1.0), (0.08, 0.13)])
def test_a_hdr_ramp_is_within_one_ten_bit_code_and_keeps_its_levels(
    tmp_path, monkeypatch, low, high
):
    if not check_zscale_available():
        pytest.skip("this FFmpeg has no zscale")
    sent, reference = rendered_and_reference(
        tmp_path, monkeypatch, sixteen_bit=True, low=low, high=high
    )
    new, old = _ten_bit_luma(sent), _ten_bit_luma(reference)

    assert np.abs(new.astype(int) - old.astype(int)).max() <= 1
    row = HEIGHT // 2
    assert len(np.unique(new[row])) >= len(np.unique(old[row]))
