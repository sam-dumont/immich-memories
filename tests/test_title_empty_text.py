"""Textless endings must not allocate or touch a full-frame text surface."""

import pytest

from immich_memories.titles.kernel_text import TitleTextRenderer
from immich_memories.titles.renderer_kernels import KernelTitleConfig


@pytest.mark.parametrize("subtitle", [None, ""])
def test_textless_render_never_touches_device_buffers(subtitle):
    class NoTextBuffers:
        @property
        def frame(self):
            pytest.fail("textless ending accessed the device frame")

        @property
        def temp(self):
            pytest.fail("textless ending accessed the composite surface")

    text = TitleTextRenderer(KernelTitleConfig(width=64, height=64), NoTextBuffers())
    text.render(1.0, 0.5, "", subtitle)
