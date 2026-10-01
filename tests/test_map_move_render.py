"""A location card's frames: the camera travels, then sits still for the hold with the name up.

Tiles are faked (a colour that follows the camera) and FFmpeg's stdin is captured, so
nothing here reaches a tile server or writes a video.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

_W, _H, _FPS = 64, 36, 10.0


def _camera_colour(lat: float, lon: float, zoom: float, w: int, h: int) -> Image.Image:
    return Image.new("RGB", (w, h), (int(lat * 2) % 256, int(lon * 2) % 256, int(zoom * 10)))


class _Pipe:
    def __init__(self) -> None:
        self.frames: list[bytes] = []
        self.stdin = MagicMock()
        self.stdin.write.side_effect = self.frames.append
        self.stderr = None
        self.returncode = 0

    def wait(self) -> int:
        return 0


def _render_card(tmp_path: Path, came_from, destination, seconds: float) -> list[bytes]:
    from immich_memories.titles.map_animation import create_map_move_video

    pipe = _Pipe()
    with (
        # WHY: replaces the satellite tile fetch, which goes to a third-party tile server
        patch("immich_memories.titles.map_animation._render_satellite", _camera_colour),
        # WHY: replaces the FFmpeg encode; the frames it would have written are what we check
        patch("immich_memories.titles.map_animation.subprocess.Popen", return_value=pipe),
        # WHY: the stderr reader thread needs a real pipe
        patch("immich_memories.titles.map_animation.StderrDrain"),
    ):
        create_map_move_video(
            came_from, destination, "Newtown", tmp_path / "card.mp4", seconds, _W, _H, _FPS
        )
    return pipe.frames


def test_a_card_flies_then_holds_still_on_the_named_place_for_two_seconds(tmp_path) -> None:
    frames = _render_card(tmp_path, (48.86, 2.35), (45.76, 4.84), 7.0)

    assert len(frames) == 70
    hold = frames[-20:]
    assert all(frame == hold[0] for frame in hold)
    assert frames[0] != hold[0]
    assert frames[10] != frames[30]


def test_the_trip_intro_lands_and_holds_on_its_named_stops(tmp_path) -> None:
    from immich_memories.processing.map_move_timing import MapMoveTiming
    from immich_memories.titles.map_animation import create_map_fly_video

    stops = [(45.76, 4.84), (43.30, 5.37)]
    seconds = MapMoveTiming().intro_seconds((48.86, 2.35), stops)
    pipe = _Pipe()
    with (
        # WHY: replaces the satellite tile fetch, which goes to a third-party tile server
        patch("immich_memories.titles.map_animation._render_satellite", _camera_colour),
        # WHY: replaces the FFmpeg encode; the frames it would have written are what we check
        patch("immich_memories.titles.map_animation.subprocess.Popen", return_value=pipe),
        # WHY: the stderr reader thread needs a real pipe
        patch("immich_memories.titles.map_animation.StderrDrain"),
    ):
        create_map_fly_video(
            (48.86, 2.35),
            stops,
            "A WEEK SOUTH",
            tmp_path / "intro.mp4",
            _W,
            _H,
            duration=seconds,
            fps=_FPS,
            destination_names=["Rivertown", "Porttown"],
        )

    assert 6.0 <= seconds <= 8.0
    assert len(pipe.frames) == round(seconds * _FPS)
    assert len(set(pipe.frames[-20:])) == 1


def _held_frame(tmp_path: Path, w: int, h: int) -> Image.Image:
    from immich_memories.processing.map_move_timing import MapMoveTiming
    from immich_memories.titles.map_animation import create_map_fly_video

    # Two stops north and south of each other, as a lakeside town and the ridge above it.
    stops = [(45.90, 6.13), (45.78, 6.08)]
    seconds = MapMoveTiming().intro_seconds((50.85, 4.35), stops)
    pipe = _Pipe()
    with (
        # WHY: replaces the satellite tile fetch, which goes to a third-party tile server
        patch("immich_memories.titles.map_animation._render_satellite", _camera_colour),
        # WHY: replaces the FFmpeg encode; the frames it would have written are what we check
        patch("immich_memories.titles.map_animation.subprocess.Popen", return_value=pipe),
        # WHY: the stderr reader thread needs a real pipe
        patch("immich_memories.titles.map_animation.StderrDrain"),
    ):
        create_map_fly_video(
            (50.85, 4.35),
            stops,
            "A WEEK IN FRANCE",
            tmp_path / "intro.mp4",
            w,
            h,
            duration=seconds,
            fps=5.0,
            destination_names=["Lakeside", "Ridge"],
        )
    return Image.frombytes("RGB", (w, h), pipe.frames[-1])


def _pin_rows(frame: Image.Image) -> list[int]:
    """Rows holding a pin's red dot, which nothing else on a fake-tile frame is."""
    return sorted(
        {
            y
            for y in range(frame.height)
            for x in range(frame.width)
            if (p := frame.getpixel((x, y)))[0] > 150 and p[0] - p[1] > 60 and p[0] - p[2] > 70
        }
    )


def test_the_held_stops_sit_clear_of_the_trip_title_in_landscape(tmp_path) -> None:
    rows = _pin_rows(_held_frame(tmp_path, 320, 180))

    assert rows, "no pin drawn"
    # The title's band starts about 63 % down a landscape frame; each name sits above its pin.
    assert rows[-1] < 0.6 * 180
    assert rows[0] >= 27


def test_the_held_stops_sit_clear_of_the_trip_title_in_portrait(tmp_path) -> None:
    rows = _pin_rows(_held_frame(tmp_path, 180, 320))

    assert rows, "no pin drawn"
    # A portrait title sits in the middle, its band from about 37 % down.
    assert rows[-1] < 0.37 * 320
    assert rows[0] >= 27


class _DiscardPipe:
    def __init__(self) -> None:
        self.stdin = self
        self.stderr = None
        self.returncode = 0

    def write(self, data: bytes) -> int:
        return len(data)

    def close(self) -> None:
        pass

    def wait(self) -> int:
        return 0


def _camera_path(tmp_path: Path, origin, destination, width: int, height: int, stops=None):
    from immich_memories.titles.map_animation import create_map_fly_video, create_map_move_video

    cameras = []

    def tiles(lat, lon, zoom, w, h):
        cameras.append((lat, lon, width / 2**zoom))
        return Image.new("RGB", (w, h), (40, 50, 60))

    with (
        # WHY: capture geographic framing at the external tile fetch boundary.
        patch("immich_memories.titles.map_animation._render_satellite", tiles),
        # WHY: geometric tests inspect every frame request without encoding a large movie.
        patch("immich_memories.titles.map_animation.subprocess.Popen", return_value=_DiscardPipe()),
        # WHY: the stderr reader requires a real encoder pipe.
        patch("immich_memories.titles.map_animation.StderrDrain"),
    ):
        if stops is None:
            create_map_move_video(
                origin, destination, "Newtown", tmp_path / "camera.mp4", 6.0, width, height, 1.0
            )
        else:
            create_map_fly_video(
                origin,
                stops,
                "A WEEK AWAY",
                tmp_path / "camera.mp4",
                width,
                height,
                duration=6.0,
                fps=1.0,
                destination_names=["Firsttown", "Lasttown"],
            )
    return cameras


def test_a_city_flight_is_close_at_both_ends_and_keeps_its_geography_at_4k(tmp_path):
    import pytest

    origin, destination = (50.85, 4.35), (48.86, 2.35)
    hd = _camera_path(tmp_path, origin, destination, 1920, 1080)
    uhd = _camera_path(tmp_path, origin, destination, 3840, 2160)

    assert hd[0][:2] == pytest.approx(origin)
    assert hd[-1][:2] == pytest.approx(destination)
    assert hd[0][2] == pytest.approx(1920 / 2**14)
    assert hd[-1][2] == pytest.approx(1920 / 2**14)
    assert max(view[2] for view in hd) > hd[0][2] * 2
    assert len(hd) == len(uhd)
    for lower, higher in zip(hd, uhd, strict=True):
        assert higher == pytest.approx(lower)


def test_the_intro_lands_close_to_its_first_stop_not_future_stops(tmp_path):
    import pytest

    from immich_memories.titles.map_animation import _geo_to_screen

    origin, paris, brest = (50.85, 4.35), (48.86, 2.35), (48.39, -4.49)
    cameras = _camera_path(tmp_path, origin, paris, 1920, 1080, [paris, brest])

    assert cameras[0][:2] == pytest.approx(origin)
    lat, lon, span = cameras[-1]
    assert span == pytest.approx(1920 / 2**14)
    sx, sy = _geo_to_screen(*paris, lat, lon, 14, 1920, 1080)
    assert 0.3 * 1920 < sx < 0.7 * 1920
    assert 0.12 * 1080 < sy < 0.6 * 1080


def test_stationary_and_nearby_towns_stay_finite_and_portrait_stays_close(tmp_path):
    import math

    import pytest

    origin = (50.85, 4.35)
    for destination in [origin, (50.851, 4.352)]:
        landscape = _camera_path(tmp_path, origin, destination, 1920, 1080)
        portrait = _camera_path(tmp_path, origin, destination, 1080, 1920)
        assert portrait[0][:2] == pytest.approx(origin)
        assert portrait[-1][:2] == pytest.approx(destination)
        for view in portrait:
            assert all(math.isfinite(value) for value in view)
            assert view[2] == pytest.approx(1080 / 2**14)
        for view in landscape:
            assert view[2] == pytest.approx(1920 / 2**14)


@pytest.mark.parametrize("dimensions", [(1920, 1080), (3840, 2160), (1080, 1920)])
def test_fast_background_policy_bounds_each_leg_to_three_small_map_views(tmp_path, dimensions):
    from immich_memories.config import Config
    from immich_memories.titles.generator import TitleScreenConfig
    from immich_memories.titles.trip_service import TripService

    resolved = Config(preset="fast")
    cfg = TitleScreenConfig(
        animated_background=resolved.title_screens.animated_background,
        resolution_width=dimensions[0],
        resolution_height=dimensions[1],
        fps=60,
    )
    cameras = []

    def tiles(lat, lon, zoom, w, h):
        cameras.append((lat, lon, w / 2**zoom, w, h))
        return Image.new("RGB", (w, h), (40, 50, 60))

    with (
        # WHY: count actual raster requests at the third-party satellite boundary.
        patch("immich_memories.titles.map_animation._render_satellite", tiles),
        # WHY: this test verifies synthesis cost and routing without an external encoder.
        patch("immich_memories.titles.map_animation.subprocess.Popen", return_value=_DiscardPipe()),
        # WHY: replaces the still-plate FFmpeg encode at the same process boundary.
        patch(
            "immich_memories.titles.map_animation.subprocess.run",
            return_value=MagicMock(returncode=0),
        ),
        # WHY: the stderr reader needs an actual encoding process.
        patch("immich_memories.titles.map_animation.StderrDrain"),
    ):
        service = TripService(cfg, MagicMock(), tmp_path)
        screen = service.generate_location_move("Paris", (50.85, 4.35), (48.86, 2.35), 7)

    assert screen.duration == 7
    assert len(cameras) == 3
    assert all(min(c[3], c[4]) <= 360 for c in cameras)
    assert cameras[0][:2] == pytest.approx((50.85, 4.35))
    assert cameras[-1][:2] == pytest.approx((48.86, 2.35))
    assert cameras[0][2] == pytest.approx(1080 / 2**14 * dimensions[0] / min(dimensions))
    assert cameras[-1][2] == pytest.approx(cameras[0][2])
    assert cameras[1][2] > cameras[0][2] * 2
