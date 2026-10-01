"""Compositing must not copy or clear surfaces that its kernels fully overwrite."""

import numpy as np
import pytest

from immich_memories.titles import kernels
from immich_memories.titles.renderer_kernels import KernelTitleConfig, KernelTitleRenderer


def test_title_and_particles_need_no_full_frame_copy_or_clear(monkeypatch):
    if not kernels.init_kernels():
        pytest.skip("no working kernel backend")
    calls = []
    original = kernels._copy_field_3

    def counted(*args):
        calls.append(True)
        return original(*args)

    # WHY: count real device launches; pixel equality alone cannot detect
    # a redundant full-frame copy, the performance bug here.
    monkeypatch.setattr(kernels, "_copy_field_3", counted)
    renderer = KernelTitleRenderer(KernelTitleConfig(width=160, height=96, blur_radius=0))
    blank = renderer.render_frame(30, "", None)
    renderer.gpu.bokeh.fill(float("nan"))
    np.testing.assert_array_equal(renderer.render_frame(30, "", None), blank)
    titled = renderer.render_frame(30, "Title", "Subtitle")
    assert np.abs(titled.astype(int) - blank).max() > 50
    assert calls == []
