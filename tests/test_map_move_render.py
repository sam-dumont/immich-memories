"""A location card's frames: the camera travels, then sits still for the hold with the name up.

Tiles are faked (a colour that follows the camera) and FFmpeg's stdin is captured, so
nothing here reaches a tile server or writes a video.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

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
