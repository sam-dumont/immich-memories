"""The ending filters only the last clip's tail, and gets the frames a whole decode gave (#2709).

`render_last_clip` keeps half a second of the last clip but ran every frame of it
through the assembly's filters. The decoder now drops the frames before its last
1.5 s right after the timestamps are reset, before any costly filter; the
frame-rate filter still places every later frame where it did.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from immich_memories.processing.streaming_frame_decoder import make_decoder
from tests.integration.conftest import requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]


def _source(path: Path, rate: int, jitter: bool, hlg: bool) -> Path:
    filters = ["setpts='PTS+(0.004*sin(N*1.7))/TB'"] if jitter else []
    if hlg:
        filters.append(
            "setparams=color_primaries=bt2020:color_trc=arib-std-b67:colorspace=bt2020nc"
        )
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", f"testsrc2=size=180x320:rate={rate}:duration=4",
            *(["-vf", ",".join(filters)] if filters else []),
            *(["-fps_mode", "vfr"] if jitter else []),
            "-c:v", "libx264", "-pix_fmt", "yuv420p10le" if hlg else "yuv420p", str(path),
        ],
        check=True, capture_output=True,
    )  # fmt: skip
    return path


@pytest.mark.parametrize(
    ("rate", "fps", "jitter", "hlg"),
    [(60, 30, False, False), (30, 30, True, False), (30, 60, False, True), (25, 30, True, True)],
)
def test_the_tail_is_the_whole_decodes_tail(tmp_path, rate, fps, jitter, hlg):
    source = _source(tmp_path / "last.mp4", rate, jitter, hlg)
    clip = SimpleNamespace(path=source, duration=4.0, is_title_screen=False)

    def frames(**kwargs) -> list[str]:
        decoder = make_decoder(
            clip, 0, 180, 320, fps, None, hdr_type="hlg" if hlg else None, **kwargs
        )
        return [hashlib.sha256(frame.tobytes()).hexdigest() for frame in decoder]

    whole = frames()
    tail = frames(from_seconds=2.5)

    kept = fps // 2
    assert tail[-kept:] == whole[-kept:]
    # Every frame the trimmed decode gives is one the whole decode gave, in place.
    assert tail == whole[-len(tail) :]
    assert len(tail) <= round(1.5 * fps) + 1
