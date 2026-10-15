"""The Ken Burns move starts on the whole picture and ends at exactly the zoom it was given.

The renderer used to scale the source by the largest zoom and a pan margin and
then cut ``window / zoom`` out of that, zooming twice: the first frame never
showed the whole photograph and the last showed 63-80 % of it, so faces near the
edges were never in the film (#2440).
"""

from __future__ import annotations

import numpy as np
import pytest

from immich_memories.photos.renderer import KenBurnsParams, render_ken_burns_streaming

# Corner markers: one colour per corner, 12 % of the side, on mid grey.
_RED, _GREEN, _BLUE, _WHITE = (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255)


def _corners(width: int, height: int) -> np.ndarray:
    img = np.full((height, width, 3), 128, dtype=np.uint8)
    mw, mh = width * 12 // 100, height * 12 // 100
    img[:mh, :mw] = _RED
    img[:mh, -mw:] = _GREEN
    img[-mh:, :mw] = _BLUE
    img[-mh:, -mw:] = _WHITE
    return img


def _frames(src, vp_w, vp_h, params, scale_mode="fit"):
    return list(render_ken_burns_streaming(src, vp_w, vp_h, params, scale_mode=scale_mode))


def _near(pixel, colour) -> bool:
    return bool(np.abs(pixel.astype(int) - np.array(colour)).max() < 40)


def _assert_corners_in(frame: np.ndarray, left: int, top: int, right: int, bottom: int) -> None:
    inset = 3
    assert _near(frame[top + inset, left + inset], _RED)
    assert _near(frame[top + inset, right - 1 - inset], _GREEN)
    assert _near(frame[bottom - 1 - inset, left + inset], _BLUE)
    assert _near(frame[bottom - 1 - inset, right - 1 - inset], _WHITE)


@pytest.mark.parametrize("pan_start", [(0.5, 0.5), (0.0, 1.0), (0.7, 0.3)])
def test_the_first_frame_shows_the_whole_picture(pan_start):
    params = KenBurnsParams(1.0, 1.12, pan_start, (1.0, 0.0), fps=4, duration=1)

    first = _frames(_corners(400, 200), 400, 200, params)[0]

    _assert_corners_in(first, 0, 0, 400, 200)


@pytest.mark.parametrize("scale_mode", ["fit", "blur"])
def test_a_portrait_starts_whole_inside_its_landscape_window(scale_mode):
    params = KenBurnsParams(1.0, 1.10, (0.3, 0.6), (0.5, 0.5), fps=4, duration=1)

    first = _frames(_corners(200, 400), 640, 360, params, scale_mode)[0]

    # The photo window: 180x360 centred in 640x360.
    _assert_corners_in(first, 230, 0, 410, 360)


@pytest.mark.parametrize("scale_mode", ["fit", "blur"])
def test_a_landscape_starts_whole_inside_its_portrait_window(scale_mode):
    params = KenBurnsParams(1.0, 1.10, (0.5, 0.5), (0.2, 0.8), fps=4, duration=1)

    first = _frames(_corners(400, 200), 360, 640, params, scale_mode)[0]

    # The photo window: 360x180 centred in 360x640.
    _assert_corners_in(first, 0, 230, 360, 410)


def _ramp(width: int, height: int) -> np.ndarray:
    """Each pixel's value says which source column it came from (16-bit, exact)."""
    column = np.linspace(0, 65535, width).astype(np.uint16)
    return np.repeat(np.repeat(column[None, :, None], height, axis=0), 3, axis=2)


def _source_column(value: float, width: int) -> float:
    return value / 65535 * (width - 1)


@pytest.mark.parametrize(
    ("zoom_end", "pan_x"), [(1.25, 0.5), (1.12, 0.0), (1.12, 1.0), (1.05, 0.3)]
)
def test_the_last_frame_is_cut_at_exactly_the_end_zoom(zoom_end, pan_x):
    width, height = 1000, 500
    params = KenBurnsParams(1.0, zoom_end, (0.5, 0.5), (pan_x, 0.5), fps=4, duration=1)

    last = _frames(_ramp(width, height), 500, 250, params)[-1]

    left = _source_column(last[125, 0, 0], width)
    right = _source_column(last[125, -1, 0], width)
    shown = width / zoom_end
    expected_left = pan_x * (width - shown)
    # Within a viewport pixel (two source pixels at this scale) at each edge.
    assert left == pytest.approx(expected_left, abs=2.5)
    assert right == pytest.approx(expected_left + shown, abs=2.5)


# ---- one continuous move ---------------------------------------------------------
#
# The renderer used to interpolate the zoom and the pan position separately, and
# read the pan as a share of the room the *current* zoom leaves. Starting from the
# whole picture that room is zero, so the view's centre barely moved until the zoom
# had built up: on screen it zoomed first and panned after (#2440).


def _progress(params: KenBurnsParams, t: float) -> tuple[float, float]:
    """How far the centre and the size have gone from start to end, each 0 to 1."""
    from immich_memories.photos.renderer import crop_window

    x0, y0, s0 = crop_window(params, 0.0)
    x1, y1, s1 = crop_window(params, 1.0)
    x, y, s = crop_window(params, t)
    travel = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
    centre = ((x - x0) ** 2 + (y - y0) ** 2) ** 0.5 / travel
    return centre, (s - s0) / (s1 - s0)


@pytest.mark.parametrize(
    "params",
    [
        KenBurnsParams(1.0, 1.3, (0.5, 0.5), (0.0, 0.2)),
        KenBurnsParams(1.45, 1.0, (1.0, 0.0), (0.5, 0.5)),
        KenBurnsParams(1.0, 1.5, (0.5, 0.5), (1.0, 1.0)),
    ],
)
@pytest.mark.parametrize("t", [0.25, 0.5, 0.75])
def test_the_view_pans_and_zooms_in_step(params, t):
    centre, size = _progress(params, t)

    assert centre == pytest.approx(size, abs=0.03)
    assert 0.05 < centre < 0.95


def test_the_view_travels_on_a_straight_line():
    from immich_memories.photos.renderer import crop_window

    params = KenBurnsParams(1.0, 1.35, (0.5, 0.5), (0.0, 1.0))
    (x0, y0, _), (x1, y1, _) = crop_window(params, 0.0), crop_window(params, 1.0)
    for t in (0.2, 0.4, 0.6, 0.8):
        x, y, _ = crop_window(params, t)
        cross = (x1 - x0) * (y - y0) - (y1 - y0) * (x - x0)
        assert abs(cross) < 1e-9


def test_the_zoom_is_perceptually_even():
    """Equal steps in time scale the view by equal ratios, so the zoom never seems to speed up."""
    from immich_memories.photos.renderer import crop_window

    params = KenBurnsParams(1.0, 1.4, (0.5, 0.5), (0.3, 0.6))
    sizes = [crop_window(params, t)[2] for t in (0.0, 0.25, 0.5, 0.75, 1.0)]
    ratios = [b / a for a, b in zip(sizes, sizes[1:], strict=False)]
    assert max(ratios) == pytest.approx(min(ratios), rel=1e-6)


def test_a_pan_at_a_fixed_zoom_moves_evenly():
    from immich_memories.photos.renderer import crop_window

    params = KenBurnsParams(1.2, 1.2, (0.0, 0.5), (1.0, 0.5))
    xs = [crop_window(params, t)[0] for t in (0.0, 0.25, 0.5, 0.75, 1.0)]
    steps = [b - a for a, b in zip(xs, xs[1:], strict=False)]
    assert max(steps) == pytest.approx(min(steps), rel=1e-6)


def test_the_middle_frame_shows_the_window_the_curve_names():
    from immich_memories.photos.renderer import crop_window

    width, height = 1000, 500
    params = KenBurnsParams(1.0, 1.3, (0.5, 0.5), (0.0, 0.5), fps=5, duration=1)
    frames = _frames(_ramp(width, height), 500, 250, params)
    middle = frames[2]  # t = 0.5 of five frames

    cx, _, size = crop_window(params, 0.5)
    left = _source_column(middle[125, 0, 0], width)
    assert left == pytest.approx((cx - size / 2) * width, abs=2.5)


# ---- a subtle easing per still ------------------------------------------------------


def _curves():
    from immich_memories.photos.renderer import EASINGS

    return sorted(EASINGS)


@pytest.mark.parametrize("name", _curves())
def test_every_easing_runs_from_start_to_end_without_turning_back(name):
    from immich_memories.photos.renderer import eased

    values = [eased(name, n / 200) for n in range(201)]
    assert values[0] == 0.0
    assert values[-1] == pytest.approx(1.0)
    assert all(b >= a for a, b in zip(values, values[1:], strict=False))


@pytest.mark.parametrize("name", _curves())
def test_no_easing_nearly_stops_at_either_end(name):
    """Both ends move at no less than 60 % of the move's average speed (1)."""
    from immich_memories.photos.renderer import eased

    h = 1e-4
    start_speed = eased(name, h) / h
    end_speed = (1.0 - eased(name, 1.0 - h)) / h
    assert min(start_speed, end_speed) >= 0.6 - 1e-3


@pytest.mark.parametrize("name", _curves())
@pytest.mark.parametrize("t", [0.25, 0.5, 0.75])
def test_size_and_centre_stay_in_step_under_every_easing(name, t):
    params = KenBurnsParams(1.0, 1.3, (0.5, 0.5), (0.0, 0.2), easing=name)

    centre, size = _progress(params, t)

    assert centre == pytest.approx(size, abs=0.03)


def test_the_easing_is_chosen_per_still_and_stays_with_it():
    from immich_memories.analysis.facts.framing_target import PictureFaces
    from immich_memories.photos.ken_burns_moves import FilmSubject, planned_move

    def easing(key: str) -> str:
        return planned_move(key, PictureFaces(), FilmSubject.OTHER, fps=10, duration=1).easing

    chosen = [easing(f"still-{n}") for n in range(60)]
    assert set(chosen) == set(_curves())
    assert easing("still-7") == chosen[7]
