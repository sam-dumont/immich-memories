"""A location card through real FFmpeg: it flies, then holds still on the named place.

The tile server is the only fake: every tile is a flat dark colour picked from its
address, so the camera's position is visible in the frames and nothing leaves
the machine.

Run: make test-integration-titles
"""

from __future__ import annotations

import io
import zlib

import numpy as np
import pytest
from PIL import Image

from immich_memories.processing.map_move_timing import MapMoveTiming
from immich_memories.titles.map_animation import create_map_move_video
from tests.integration.titles.conftest import extract_frame_rgb, ffprobe_stream

pytestmark = [pytest.mark.integration]

_W, _H, _FPS = 320, 180, 10.0


def _tile(_self, url: str, **_kwargs) -> tuple[int, bytes]:
    shade = zlib.crc32(url.encode())
    image = Image.new("RGB", (256, 256), (shade & 0x7F, (shade >> 8) & 0x7F, (shade >> 16) & 0x7F))
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return 200, buffer.getvalue()


def test_a_card_moves_then_holds_two_still_seconds_with_its_name(tmp_path, monkeypatch) -> None:
    import staticmap

    # WHY: the tile server is a third-party host; tiles are the one outside read.
    monkeypatch.setattr(staticmap.StaticMap, "get", _tile)
    timing = MapMoveTiming()
    seconds = timing.seconds_between((48.86, 2.35), (45.76, 4.84))
    out = create_map_move_video(
        (48.86, 2.35), (45.76, 4.84), "Rivertown", tmp_path / "card.mp4", seconds, _W, _H, _FPS
    )

    duration = float(ffprobe_stream(out)["duration"])
    total = round(seconds * _FPS)
    first, moving = (extract_frame_rgb(out, i, _W, _H) for i in (0, total // 3))
    hold = [extract_frame_rgb(out, i, _W, _H) for i in (total - 20, total - 10, total - 1)]

    assert 6.0 <= duration <= 8.1
    assert np.abs(first.astype(int) - moving.astype(int)).mean() > 5
    for frame in hold[1:]:
        assert np.abs(frame.astype(int) - hold[0].astype(int)).mean() < 1.0
    # The name sits in the lower third during the hold: bright text over a dark band.
    label_rows = hold[0][int(_H * 0.62) : int(_H * 0.82)]
    assert label_rows.max() > 200
