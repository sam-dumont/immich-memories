"""The slow-mo blend belongs on the device, and must land in the same place.

The background of a content-backed title interpolates between a handful of
source frames — 15 of them serve 105 output frames. That blend ran in numpy,
ten passes over 25 MB arrays per output frame, and the f32 result was uploaded
every frame: 14.9ms per frame against 3.3ms for a plain gradient. The sources
never change, so they belong on the device.
"""

from __future__ import annotations

import numpy as np
import pytest

ti_kernels = pytest.importorskip("immich_memories.titles.kernels")


@pytest.fixture(scope="module")
def kernels_ready() -> bool:
    if not ti_kernels.init_kernels():
        pytest.skip("the kernel library has no working backend here")
    return True


def _numpy_catmull_rom(sources: list[np.ndarray], window: tuple, t: float) -> np.ndarray:
    """The interpolation the GPU kernel replaces, kept here as the reference."""
    scale = float(np.iinfo(sources[0].dtype).max)
    p0, p1, p2, p3 = (sources[i].astype(np.float32) / scale for i in window)
    out = 0.5 * (
        2.0 * p1
        + (-p0 + p2) * t
        + (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * (t * t)
        + (-p0 + 3.0 * p1 - 3.0 * p2 + p3) * (t * t * t)
    )
    return np.clip(out, 0.0, 1.0)


@pytest.mark.parametrize("dtype", [np.uint8, np.uint16])
def test_the_device_blend_matches_the_one_it_replaces(kernels_ready: bool, dtype) -> None:
    rng = np.random.default_rng(7)
    height, width, count = 64, 96, 8
    sources = [
        rng.integers(0, np.iinfo(dtype).max + 1, size=(height, width, 3), dtype=dtype)
        for _ in range(count)
    ]
    gpu = ti_kernels.GPUBuffers(height, width)
    assert gpu.load_sources(sources)

    worst = 0.0
    for idx in range(1, count - 2):
        for t in (0.0, 0.25, 0.5, 0.9):
            window = (idx - 1, idx, idx + 1, idx + 2)
            gpu.blend_sources(window, t)
            reference = _numpy_catmull_rom(sources, window, t)
            worst = max(worst, float(np.abs(gpu.frame.to_numpy() - reference).max()))

    assert worst < 1e-5, f"device blend drifted from the reference by {worst}"


def test_sources_of_the_wrong_shape_are_refused(kernels_ready: bool) -> None:
    """A refusal keeps the numpy path; a wrong-shaped upload would corrupt frames."""
    gpu = ti_kernels.GPUBuffers(64, 96)

    assert not gpu.load_sources([])
    assert not gpu.load_sources([np.zeros((10, 10, 3), dtype=np.uint8)])
    assert not gpu.load_sources([np.zeros((64, 96, 3), dtype=np.float32)])


@pytest.mark.parametrize("dtype", [np.uint8, np.uint16])
def test_source_window_stays_bounded_and_handles_repeated_edges(kernels_ready, dtype):
    sources = [np.full((4, 6, 3), i * 11, dtype=dtype) for i in range(20)]
    gpu = ti_kernels.GPUBuffers(4, 6)
    assert gpu.load_sources(sources)
    assert gpu.sources.shape[0] <= 4
    for window in ((0, 0, 1, 2), (1, 2, 3, 4), (17, 18, 19, 19), (0, 0, 0, 0)):
        gpu.blend_sources(window, 0.5)
        np.testing.assert_allclose(
            gpu.frame.to_numpy(), _numpy_catmull_rom(sources, window, 0.5), atol=1e-6
        )


@pytest.mark.parametrize(
    "bad_frame",
    [
        np.zeros((4, 6, 4), dtype=np.uint16),
        np.zeros((4, 6, 3), dtype=np.uint8),
        np.zeros((6, 4, 3), dtype=np.uint16),
    ],
)
def test_mixed_sources_fall_back_before_upload(kernels_ready, bad_frame):
    gpu = ti_kernels.GPUBuffers(4, 6)
    assert not gpu.load_sources([np.zeros((4, 6, 3), dtype=np.uint16), bad_frame])


def test_hdr_title_pixels_match_the_numpy_reader_path(kernels_ready):
    from immich_memories.titles.renderer_kernels import KernelTitleConfig, KernelTitleRenderer

    rng = np.random.default_rng(19)
    sources = [rng.integers(0, 65536, (64, 96, 3), dtype=np.uint16) for _ in range(8)]
    windows = [
        ((max(0, i - 1), i, i + 1, min(7, i + 2)), t)
        for i in range(7)
        for t in (0.0, 0.25, 0.5, 0.75)
    ]

    class ResidentReader:
        source_frames = sources

        def __init__(self):
            self.windows = iter(windows)

        def next_blend(self):
            return next(self.windows, None)

    class NumpyReader:
        def __init__(self):
            self.windows = iter(windows)

        def read_frame(self):
            indices, t = next(self.windows)
            return _numpy_catmull_rom(sources, indices, t)

    def renderer(reader):
        return KernelTitleRenderer(
            KernelTitleConfig(
                width=96,
                height=64,
                fps=10,
                duration=2.8,
                hdr=True,
                background_reader=reader,
                blur_radius=8,
            )
        )

    resident, reference = renderer(ResidentReader()), renderer(NumpyReader())
    for number in range(len(windows)):
        actual = resident.render_frame(number, "Title", "Subtitle")
        expected = reference.render_frame(number, "Title", "Subtitle")
        np.testing.assert_allclose(actual, expected, atol=2, rtol=0)
