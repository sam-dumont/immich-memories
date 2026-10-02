"""The faster PQ stage must preserve HLG's accurate display transform."""

import subprocess

import numpy as np
import pytest

from immich_memories.processing.hdr_utilities import (
    check_zscale_available,
    get_hdr_conversion_filter,
)
from tests.integration.conftest import requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]

_ACCURATE = (
    "zscale=tin=arib-std-b67:t=smpte2084"
    ":pin=bt2020:p=bt2020:min=bt2020nc:m=bt2020nc:npl=203:agamma=false"
)


@pytest.mark.parametrize(
    ("pattern", "signal_range"),
    [
        ("nullsrc=s=128x72,format=yuv420p10le,geq=lum=64+876*X/W:cb=512:cr=512", "limited"),
        ("nullsrc=s=128x72,format=yuv420p10le,geq=lum=1023*X/W:cb=512:cr=512", "limited"),
        ("nullsrc=s=128x72,format=yuv420p10le,geq=lum=1023*X/W:cb=512:cr=512", "full"),
        ("testsrc2=s=128x72,format=yuv420p10le", "limited"),
    ],
    ids=["nominal-ramp", "excursion-ramp", "full-range-ramp", "saturated-colors"],
)
def test_hlg_to_pq_pixels_stay_within_one_code_value(pattern, signal_range):
    if not check_zscale_available():
        pytest.skip("FFmpeg zscale is unavailable")
    source = (
        f"{pattern},setparams=range={signal_range}:color_primaries=bt2020"
        ":color_trc=arib-std-b67:colorspace=bt2020nc"
    )
    candidate = get_hdr_conversion_filter("hlg", "pq", required=True).lstrip(",")
    frames = []
    for conversion in [_ACCURATE, candidate]:
        result = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-filter_threads",
                "1",
                "-f",
                "lavfi",
                "-i",
                source,
                "-vf",
                f"{conversion},format=yuv420p10le",
                "-frames:v",
                "1",
                "-f",
                "rawvideo",
                "-",
            ],
            check=True,
            capture_output=True,
            timeout=20,
        )
        frame = np.frombuffer(result.stdout, dtype="<u2").astype(np.int32)
        assert frame.size == 128 * 72 * 3 // 2
        frames.append(frame)

    assert np.max(np.abs(frames[1] - frames[0])) <= 1
