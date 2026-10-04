"""Tests for titles/map_animation.py coordinate math and interpolation."""

from __future__ import annotations

import numpy as np
from PIL import Image

from immich_memories.titles.map_animation import (
    _MIN_PIN_LABEL_RATIO,
    _PIN_LABEL_SHARE,
    _cached_pin_label_font,
    _destination_overview,
    _draw_pins,
    _FlyConfig,
    _geo_to_screen,
    _linear_pan,
    _pick_interpolator,
    _PinData,
    _to_latlon,
    _to_world,
    _van_wijk,
)


class TestWebMercator:
    def test_round_trip_equator(self):
        """to_world → to_latlon should recover the original coordinates."""
        lat, lon = 0.0, 0.0
        wx, wy = _to_world(lat, lon)
        recovered_lat, recovered_lon = _to_latlon(wx, wy)

        assert abs(recovered_lat - lat) < 0.001
        assert abs(recovered_lon - lon) < 0.001

    def test_round_trip_paris(self):
        lat, lon = 48.8566, 2.3522
        wx, wy = _to_world(lat, lon)
        recovered_lat, recovered_lon = _to_latlon(wx, wy)

        assert abs(recovered_lat - lat) < 0.001
        assert abs(recovered_lon - lon) < 0.001

    def test_round_trip_southern_hemisphere(self):
        lat, lon = -33.8688, 151.2093  # Sydney
        wx, wy = _to_world(lat, lon)
        recovered_lat, recovered_lon = _to_latlon(wx, wy)

        assert abs(recovered_lat - lat) < 0.001
        assert abs(recovered_lon - lon) < 0.001


class TestScreenProjection:
    def test_center_of_screen_at_same_position(self):
        """A pin at the camera position should project to screen center."""
        lat, lon = 48.8566, 2.3522
        sx, sy = _geo_to_screen(lat, lon, lat, lon, zoom=10, w=1920, h=1080)

        assert abs(sx - 960) < 2
        assert abs(sy - 540) < 2


class TestVanWijkInterpolator:
    def test_starts_at_origin(self):
        """f(0) should return the start view."""
        p0 = (100.0, 100.0, 10.0)
        p1 = (200.0, 200.0, 10.0)
        interp = _van_wijk(p0, p1)

        cx, cy, w = interp(0.0)

        assert abs(cx - p0[0]) < 0.01
        assert abs(cy - p0[1]) < 0.01

    def test_ends_at_destination(self):
        """f(1) should return the end view."""
        p0 = (100.0, 100.0, 10.0)
        p1 = (200.0, 200.0, 10.0)
        interp = _van_wijk(p0, p1)

        cx, cy, w = interp(1.0)

        assert abs(cx - p1[0]) < 0.5
        assert abs(cy - p1[1]) < 0.5


class TestLinearPan:
    def test_starts_at_origin(self):
        p0 = (100.0, 100.0, 5.0)
        p1 = (110.0, 110.0, 5.0)
        interp = _linear_pan(p0, p1)

        cx, cy, w = interp(0.0)

        assert abs(cx - p0[0]) < 0.01
        assert abs(cy - p0[1]) < 0.01

    def test_ends_at_destination(self):
        p0 = (100.0, 100.0, 5.0)
        p1 = (110.0, 110.0, 5.0)
        interp = _linear_pan(p0, p1)

        cx, cy, w = interp(1.0)

        assert abs(cx - p1[0]) < 0.01
        assert abs(cy - p1[1]) < 0.01


class TestPickInterpolator:
    def test_short_hop_uses_linear_pan(self):
        """Nearby points should use linear pan (mid-zoom stays high)."""
        lat0, lon0 = 48.856, 2.352  # Paris center
        lat1, lon1 = 48.860, 2.360  # ~500m away
        p0 = (*_to_world(lat0, lon0), 1920 / (2**14))
        p1 = (*_to_world(lat1, lon1), 1920 / (2**14))

        interp = _pick_interpolator(p0, p1)

        # Linear pan: viewport width stays constant (max of the two inputs)
        _, _, w_mid = interp(0.5)
        assert w_mid >= max(p0[2], p1[2])


class TestDestinationOverview:
    def test_contains_all_destinations(self):
        """Overview should produce a view that covers all destinations."""
        destinations = [(48.856, 2.352), (35.676, 139.650), (-33.868, 151.209)]

        cx, cy, w = _destination_overview(destinations, 1920, 1080)

        for lat, lon in destinations:
            wx, wy = _to_world(lat, lon)
            assert abs(wx - cx) < w, f"Destination ({lat},{lon}) outside overview x"
            assert abs(wy - cy) < w, f"Destination ({lat},{lon}) outside overview y"


class TestPinLabelFit:
    """A pin name near the frame edge stays clamped inside it (#1954).

    A centered label on a pin close to the edge overflows the frame before
    the fix — centering never checked whether the label's half-width ran
    past x=0 or x=w. Width 1080, height 1920 matches a real portrait card.
    """

    _W, _H, _ZOOM = 1080, 1920, 10.0
    _LAT, _LON = 48.8566, 2.3522

    def _cam_putting_pin_near_right_edge(self) -> tuple[float, float]:
        scale = 2.0**self._ZOOM
        pw, py_w = _to_world(self._LAT, self._LON)
        target_dx_px = (self._W - 50) - self._W / 2
        cw = pw - target_dx_px / scale
        return _to_latlon(cw, py_w)

    def _frame_with_pin(self, name: str, cam_lat: float, cam_lon: float) -> np.ndarray:
        cfg = _FlyConfig(
            pins=[_PinData(lat=self._LAT, lon=self._LON, name=name)],
            width=self._W,
            height=self._H,
            dest_zoom=self._ZOOM,
        )
        frame = Image.new("RGB", (self._W, self._H), (20, 20, 20))
        out = _draw_pins(frame, cam_lat, cam_lon, zoom=self._ZOOM, cfg=cfg)
        return np.array(out)

    def test_a_short_label_is_unaffected(self):
        """A short name is not shrunk: same font size as the unfitted base size."""
        from PIL import ImageDraw

        from immich_memories.titles.map_renderer import _get_font

        base_size = max(12, int(min(self._W, self._H) * _PIN_LABEL_SHARE))
        margin = int(self._W * 0.02)
        max_width = self._W - 2 * margin
        min_size = max(6, int(self._W * _MIN_PIN_LABEL_RATIO))

        font, width = _cached_pin_label_font("Nice", base_size, max_width, min_size)

        assert font.size == base_size
        reference_font = _get_font(base_size, bold=True)
        probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        assert width == probe.textbbox((0, 0), "Nice", font=reference_font)[2]

    def test_a_long_label_near_the_edge_does_not_reach_the_frame_edge(self):
        cam_lat, cam_lon = self._cam_putting_pin_near_right_edge()
        arr = self._frame_with_pin("Saint-Jean-Cap-Ferrat", cam_lat, cam_lon)
        margin = 3
        edge_pixels = np.concatenate([arr[:, :margin], arr[:, -margin:]], axis=1)
        assert edge_pixels.max() < 150, "Pin label overflowed the frame edge"
