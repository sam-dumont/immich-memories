"""Integer-depth rendering keeps a gradient's pixels: at most one pipe code from float (#1527).

The reference is the float32 path the renderer used before: the same Ken Burns
move over the source scaled to 0-1, then x65535 (or x255) and truncated.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from immich_memories.api.models import AssetType
from immich_memories.config_models_render import PhotoConfig
from immich_memories.photos import photo_pipeline, renderer
from immich_memories.processing import hdr_utilities
from tests.conftest import make_asset

WIDTH, HEIGHT = 360, 640


def ramp(path: Path, *, sixteen_bit: bool, low: float, high: float) -> np.ndarray:
    """A horizontal ramp written as PNG; returns the stored RGB codes."""
    full = 65535 if sixteen_bit else 255
    row = np.round(np.linspace(low, high, 480) * full)
    rgb = np.broadcast_to(row[None, :, None], (360, 480, 3))
    codes = rgb.astype(np.uint16 if sixteen_bit else np.uint8)
    cv2.imwrite(str(path), np.ascontiguousarray(codes[:, :, ::-1]))
    return codes


def rendered_and_reference(tmp_path, monkeypatch, *, sixteen_bit: bool, low: float, high: float):
    """The middle frame the pipe receives, and the float path's frame for the same move."""
    source = tmp_path / "ramp.png"
    codes = ramp(source, sixteen_bit=sixteen_bit, low=low, high=high)
    full = 65535 if sixteen_bit else 255
    moves = []
    frames = []
    real_render = renderer.render_ken_burns_streaming

    def spy(src, width, height, params):
        moves.append(params)
        return real_render(src, width, height, params)

    def pipe(cmd, sent, **_kwargs):
        frames.extend(bytes(frame) for frame in sent)
        Path(cmd[-1]).write_bytes(b"\0" * 200)
        return 0, ""

    # WHY: the ffmpeg process is the write boundary; the test reads what reaches it.
    monkeypatch.setattr(photo_pipeline, "write_frames_to_ffmpeg", pipe)
    # WHY: zscale on this machine decides the pipe format; the test picks the pipe.
    monkeypatch.setattr(hdr_utilities, "check_zscale_available", lambda: True)
    monkeypatch.setattr(photo_pipeline, "render_ken_burns_streaming", spy)
    if sixteen_bit:
        prepare = photo_pipeline._prepared_photo_pixels

        def gain_mapped(*args):
            prepared, img = prepare(*args)
            prepared.has_gain_map = True
            return prepared, img

        monkeypatch.setattr(photo_pipeline, "_prepared_photo_pixels", gain_mapped)

    asset = make_asset("ramp", original_file_name=source.name).model_copy(
        update={"type": AssetType.IMAGE}
    )
    clip = photo_pipeline.render_single_photo(
        asset, PhotoConfig(duration=1.0), WIDTH, HEIGHT, tmp_path, None, source_path=source
    )
    assert clip is not None
    middle = len(frames) // 2
    dtype = np.uint16 if sixteen_bit else np.uint8
    sent = np.frombuffer(frames[middle], dtype).reshape(HEIGHT, WIDTH, 3)
    reference_frames = real_render(codes.astype(np.float32) / full, WIDTH, HEIGHT, moves[0])
    for _ in range(middle):
        next(reference_frames)
    reference = np.clip(next(reference_frames) * full, 0, full).astype(dtype)
    return sent, reference


@pytest.mark.parametrize(
    ("sixteen_bit", "low", "high"),
    [
        (True, 0.0, 1.0),  # the full HDR range
        (True, 0.08, 0.13),  # an HDR sky: 100-130 nits of a 1000-nit peak
        (False, 0.0, 1.0),
        (False, 0.55, 0.64),  # an SDR sky: about 23 codes across the frame
    ],
)
def test_a_ramp_reaches_the_pipe_within_one_code_of_the_float_path(
    tmp_path, monkeypatch, sixteen_bit, low, high
):
    sent, reference = rendered_and_reference(
        tmp_path, monkeypatch, sixteen_bit=sixteen_bit, low=low, high=high
    )
    assert np.abs(sent.astype(np.int64) - reference.astype(np.int64)).max() <= 1
