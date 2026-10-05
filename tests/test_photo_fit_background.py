"""`scale_mode: fit` letterboxes a still on black, as it does a video (#2132).

The photo renderer filled every band with the photograph's own blur whatever the scale
mode, so `runs render --scale-mode fit` and `generate --scale-mode fit` still showed
blurred bands around every still that did not match the canvas.
"""

from __future__ import annotations

import numpy as np

from immich_memories.photos.renderer import KenBurnsParams, render_ken_burns_streaming

CANVAS_W, CANVAS_H = 320, 180


def _portrait_frame(scale_mode: str | None) -> np.ndarray:
    photo = np.full((400, 300, 3), 200, dtype=np.uint8)
    params = KenBurnsParams(fps=4, duration=1.0)
    kwargs = {} if scale_mode is None else {"scale_mode": scale_mode}
    return next(iter(render_ken_burns_streaming(photo, CANVAS_W, CANVAS_H, params, **kwargs)))


def test_fit_leaves_the_bands_beside_a_portrait_still_black():
    frame = _portrait_frame("fit")

    assert frame[:, :10].max() == 0
    assert frame[:, -10:].max() == 0
    assert frame[CANVAS_H // 2, CANVAS_W // 2].min() > 150


def test_blur_still_fills_the_bands_from_the_photograph():
    frame = _portrait_frame("blur")

    assert frame[:, :10].mean() > 100


def test_blur_is_the_default():
    assert np.array_equal(_portrait_frame(None), _portrait_frame("blur"))


def _rendered_scale_mode(tmp_path, monkeypatch, *, requested: str | None, configured: str) -> str:
    from unittest.mock import MagicMock

    from immich_memories.api.models import AssetType
    from immich_memories.config_loader import Config
    from immich_memories.generate import GenerationParams
    from immich_memories.generate_clips import extract_clips
    from tests.conftest import make_clip

    clip = make_clip("still", duration=4.0)
    clip.asset.type = AssetType.IMAGE
    config = Config()
    config.defaults.scale_mode = configured
    params = GenerationParams(
        clips=[clip],
        output_path=tmp_path / "memory.mp4",
        config=config,
        client=MagicMock(),
        clip_segments={clip.asset.id: (0.0, 4.0)},
        scale_mode=requested,
    )
    # WHY: the encode writes a file; the scale mode it is handed is what is under test.
    render = MagicMock(return_value=None)
    monkeypatch.setattr("immich_memories.photos.photo_pipeline.render_single_photo", render)
    monkeypatch.setattr(
        "immich_memories.generate_photos.detect_photo_resolution", lambda *_: (1920, 1080)
    )
    extract_clips(params, None, tmp_path)
    return render.call_args.kwargs["scale_mode"]


def test_a_render_asked_to_fit_renders_its_stills_fitted(tmp_path, monkeypatch):
    assert _rendered_scale_mode(tmp_path, monkeypatch, requested="fit", configured="blur") == "fit"


def test_without_a_request_the_stills_follow_the_configured_mode(tmp_path, monkeypatch):
    assert _rendered_scale_mode(tmp_path, monkeypatch, requested=None, configured="fit") == "fit"
