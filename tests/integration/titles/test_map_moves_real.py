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


def test_cheap_map_keeps_the_route_exact_frames_silent_audio_and_arrival_hold(
    tmp_path, monkeypatch
):
    import subprocess

    import staticmap

    from immich_memories.titles.map_animation import create_map_fly_video

    # WHY: deterministic tiles replace only the third-party HTTP read, not raster/encode.
    monkeypatch.setattr(staticmap.StaticMap, "get", _tile)
    duration = 6.0
    out = create_map_fly_video(
        (50.85, 4.35),
        [(48.86, 2.35), (48.39, -4.49)],
        "A WEEK AWAY",
        tmp_path / "cheap-intro.mp4",
        _W,
        _H,
        duration,
        _FPS,
        destination_names=["Paris", "Brest"],
        animated_background=False,
    )
    video = ffprobe_stream(out)
    assert int(video["nb_frames"]) == 60
    assert float(video["duration"]) == pytest.approx(duration)
    first, overview, arrival = (extract_frame_rgb(out, i, _W, _H) for i in [0, 25, 40])
    assert np.abs(first.astype(int) - overview.astype(int)).mean() > 5
    assert np.abs(overview.astype(int) - arrival.astype(int)).mean() > 5
    for i in [45, 55, 59]:
        frame = extract_frame_rgb(out, i, _W, _H)
        assert np.abs(frame.astype(int) - arrival.astype(int)).mean() < 1.0
    assert arrival[int(_H * 0.65) : int(_H * 0.85)].max() > 200
    audio = subprocess.check_output(
        [
            "ffmpeg",
            "-v",
            "error",
            "-xerror",
            "-i",
            str(out),
            "-map",
            "0:a:0",
            "-f",
            "f32le",
            "-acodec",
            "pcm_f32le",
            "-",
        ]
    )
    assert len(audio) > 0
    assert np.abs(np.frombuffer(audio, dtype="float32")).max() < 1e-6


def test_cheap_card_preserves_an_explicit_hdr_plan_in_portrait(tmp_path, monkeypatch):
    from dataclasses import replace

    import staticmap

    from immich_memories.processing.encoding_plan import HdrTransfer, OutputCodec
    from immich_memories.titles.encoding import standalone_title_encoding_plan

    # WHY: replace third-party HTTP tiles while keeping the real HDR encode/conversion.
    monkeypatch.setattr(staticmap.StaticMap, "get", _tile)
    plan = replace(
        standalone_title_encoding_plan(),
        codec=OutputCodec.H265,
        encoder="libx265",
        encoder_args=("-preset", "ultrafast", "-crf", "20"),
        target_transfer=HdrTransfer.PQ,
        pixel_format="yuv420p10le",
    )
    out = create_map_move_video(
        (50.85, 4.35),
        (50.86, 4.36),
        "Newtown",
        tmp_path / "hdr-card.mp4",
        6,
        180,
        320,
        10,
        encoding_plan=plan,
        animated_background=False,
    )
    stream = ffprobe_stream(out)
    assert stream["codec_name"] == "hevc"
    assert stream["pix_fmt"] == "yuv420p10le"
    assert stream["color_transfer"] == "smpte2084"
    assert stream["color_primaries"] == "bt2020"
    assert (stream["width"], stream["height"], int(stream["nb_frames"])) == (180, 320, 60)
    import subprocess

    from immich_memories.processing.hdr_utilities import get_hdr_conversion_filter

    # PQ samples are not SDR brightness values; review them through the production conversion.
    conversion = get_hdr_conversion_filter("pq", "sdr", source_primaries="bt2020", required=True)
    pixels = subprocess.check_output(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(out),
            "-vf",
            f"select=eq(n\\,59),{conversion.removeprefix(',')},format=rgb24",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-",
        ]
    )
    frame = np.frombuffer(pixels, dtype="uint8").reshape(320, 180, 3)
    assert frame.max() > 150
    assert frame.mean() > 5
