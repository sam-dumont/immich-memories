"""The feature suite's legal-range probe passes a legal film and fails a superwhite one (#2440).

The gain-mapped still's SDR film used to be held to its single brightest decoded pixel,
which H.264 pushes a few codes past 235 at any hard white edge however legal the source:
real-Immich runs read 236 and 241 on a correctly tone-mapped still. The probe now reads
the 99.5th percentile. These films show it still catches what the check is for: a picture
whose highlights really sit above legal white, here the classic range bug of full-range
codes written into a limited-range stream.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest

from tests.integration.features.film_probe import luma_levels, luma_percentile

_W, _H = 640, 360


def _picture() -> bytes:
    """Dark grey with a hard-edged white block over 15 % of the frame."""
    frame = np.full((_H, _W, 3), 60, dtype=np.uint8)
    frame[90:270, 200:388] = 255
    return frame.tobytes()


def _film(path: Path, chain: str) -> Path:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24"]
        + ["-s", f"{_W}x{_H}", "-r", "10", "-i", "pipe:0", "-frames:v", "10", "-vf", chain]
        + ["-c:v", "libx264", "-crf", "23", str(path)],
        input=_picture() * 10,
        check=True,
    )
    return path


_LEGAL = "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p"
# Full-range codes tagged as limited range: white lands on 255, a superwhite.
_SUPERWHITE = "scale=out_color_matrix=bt709:out_range=pc,format=yuv420p,setparams=range=tv"


def test_a_legal_film_passes_even_where_the_codec_rings(tmp_path):
    film = _film(tmp_path / "legal.mp4", _LEGAL)

    assert luma_percentile(film, 0.5, 99.5) <= 235


def test_a_superwhite_film_fails(tmp_path):
    film = _film(tmp_path / "superwhite.mp4", _SUPERWHITE)

    assert luma_percentile(film, 0.5, 99.5) > 235
    # The old measure agreed here; it is the legal film it got wrong.
    assert luma_levels(film, 0.5)[1] > 235


@pytest.mark.parametrize("percent", [99.0, 99.5])
def test_the_percentile_reads_the_white_block_not_the_ringing(tmp_path, percent):
    legal = _film(tmp_path / "legal.mp4", _LEGAL)

    assert luma_percentile(legal, 0.5, percent) == pytest.approx(235, abs=2)
