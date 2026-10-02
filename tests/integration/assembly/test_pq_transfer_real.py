"""The fast SDR-to-PQ transfer stays close to the accurate color reference."""

import subprocess

import numpy as np
import pytest

from immich_memories.processing.hdr_utilities import get_hdr_conversion_filter
from tests.integration.conftest import requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]


def _render_transfer(
    graph: str, source: str = "testsrc2=size=256x144:rate=1,format=yuv420p10le"
) -> np.ndarray:
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            source,
            "-vf",
            graph.removeprefix(","),
            "-frames:v",
            "1",
            "-pix_fmt",
            "yuv420p10le",
            "-f",
            "rawvideo",
            "-",
        ],
        check=True,
        capture_output=True,
        timeout=20,
    )
    return np.frombuffer(result.stdout, dtype="<u2").astype(np.int32)


@pytest.mark.parametrize(
    "source",
    [
        "testsrc2=size=256x144:rate=1,format=yuv420p10le",
        "smptehdbars=size=256x144:rate=1,format=yuv420p10le",
        "nullsrc=size=256x144:rate=1,format=yuv420p10le,geq=lum=64+876*X/W:cb=512:cr=512",
    ],
)
def test_known_bt709_sdr_to_pq_uses_fast_transfer_with_bounded_color_error(source):
    conversion = get_hdr_conversion_filter("sdr", "pq", source_primaries="bt709", required=True)
    # This is a performance policy: wall-clock assertions vary with CI load.
    assert "agamma=true" in conversion
    accurate = (
        "zscale=tin=bt709:t=smpte2084:pin=bt709:p=bt2020:min=bt709:m=bt2020nc"
        ":rin=tv:r=tv:npl=203:agamma=false"
    )
    delta = np.abs(_render_transfer(conversion, source) - _render_transfer(accurate, source))
    assert delta.size == 256 * 144 * 3 // 2
    assert delta.max() <= 8
    assert delta.mean() < 0.03


@pytest.mark.parametrize(
    ("source", "target", "primaries"),
    [
        ("sdr", "hlg", "bt709"),
        ("sdr", "hlg", "smpte432"),
        ("pq", "hlg", "bt2020"),
        ("sdr", "pq", None),
        ("sdr", "pq", "smpte432"),
        ("sdr", "pq", "bt2020"),
    ],
)
def test_unqualified_transfers_keep_reference_gamma(source, target, primaries):
    conversion = get_hdr_conversion_filter(
        source, target, source_primaries=primaries, required=True
    )
    assert "agamma=false" in conversion
    assert "agamma=true" not in conversion


@pytest.mark.parametrize(("gib", "max_error"), [(3, 0), (4, 1)])
def test_hlg_to_pq_keeps_display_referred_pixels(tmp_path, monkeypatch, gib, max_error):
    from immich_memories.processing import memory_budget

    cgroup = tmp_path / "cgroup"
    cgroup.mkdir()
    (cgroup / "memory.max").write_text(str(gib * 2**30))
    # WHY: Exercise the real resource-file reader for each transfer policy.
    monkeypatch.setattr(memory_budget, "_CGROUP", cgroup)
    conversion = get_hdr_conversion_filter("hlg", "pq", source_primaries="bt2020", required=True)
    accurate = (
        "zscale=tin=arib-std-b67:t=smpte2084:pin=bt2020:p=bt2020:min=bt2020nc:m=bt2020nc"
        ":npl=203:agamma=false"
    )
    assert ("format=gbrpf32le" in conversion) is (gib == 4)
    delta = np.abs(_render_transfer(conversion) - _render_transfer(accurate))
    assert delta.size == 256 * 144 * 3 // 2
    assert delta.max() <= max_error
