"""Pixel facts are measured side by side and banked in the order they were asked for."""

from __future__ import annotations

import io
import threading

from PIL import Image

from immich_memories.analysis.preparation.pixels import measured_rows, pixel_row


def _jpeg(shade: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), (shade, 90, 40)).save(buffer, "JPEG")
    return buffer.getvalue()


def test_two_pictures_are_measured_at_once_and_come_back_in_order():
    # Both of the first two reads must be in flight together for either to return.
    together = threading.Barrier(2, timeout=10)
    previews = {f"p{shade}": _jpeg(shade) for shade in (10, 120, 240)}

    def preview_for(asset_id: str) -> bytes:
        if asset_id in ("p10", "p120"):
            together.wait()
        if asset_id == "p240":
            raise OSError("gone")
        return previews[asset_id]

    rows = list(measured_rows(list(previews), preview_for, check=lambda: None, workers=2))

    assert [asset_id for asset_id, _row in rows] == ["p10", "p120", "p240"]
    measured = dict(rows)
    assert isinstance(measured["p240"], OSError)
    for asset_id in ("p10", "p120"):
        expected = pixel_row(asset_id, previews[asset_id])
        assert {k: v for k, v in measured[asset_id].items() if k != "computed_at"} == {
            k: v for k, v in expected.items() if k != "computed_at"
        }
