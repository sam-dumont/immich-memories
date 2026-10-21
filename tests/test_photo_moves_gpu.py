"""A photo move is cut on the GPU when the kernel library runs on one, on the CPU otherwise.

The GPU cuts the same views the CPU would, and a GPU that fails part-way hands
the rest of the move to the CPU without a gap or a repeated frame.
"""

from __future__ import annotations

import logging
import sys
import threading
import types
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from immich_memories.photos import gpu_moves
from immich_memories.photos.renderer import (
    KenBurnsParams,
    cut_frame,
    ken_burns_frames,
    ken_burns_layers,
    move_frames,
)

# Captured before the suite pins photo moves to the CPU for every test.
REAL_GPU_CUTTER = gpu_moves.gpu_cutter
PARAMS = KenBurnsParams(
    zoom_start=1.0, zoom_end=1.15, pan_start=(0.2, 0.4), pan_end=(0.7, 0.5), fps=10, duration=1.0
)


def _layers(scale_mode: str = "blur", shape=(300, 200, 3)):
    rng = np.random.default_rng(2760)
    picture = (rng.random(shape) * 255).astype(np.uint8)
    return ken_burns_layers(picture, 320, 180, PARAMS, scale_mode=scale_mode)


class _Cutter:
    """Stands in for the device: cuts on the CPU and counts, or fails from a given frame."""

    def __init__(self, layers, fail_from: int | None = None, error=RuntimeError) -> None:
        self.layers, self.fail_from, self.error, self.cuts = layers, fail_from, error, 0
        self.closed = False

    def cut(self, view):
        if self.fail_from is not None and self.cuts >= self.fail_from:
            raise self.error("device lost")
        self.cuts += 1
        frame = cut_frame(self.layers, view)
        frame[0, 0, 0] = 7  # marks a frame as the cutter's
        return frame

    def close(self):
        self.closed = True


@pytest.mark.parametrize("scale_mode", ["blur", "fit"])
def test_without_gpu_kernels_the_move_is_cut_on_the_cpu(scale_mode):
    layers = _layers(scale_mode)

    frames = list(move_frames(layers, PARAMS))
    expected = list(ken_burns_frames(layers, PARAMS))

    assert len(frames) == len(expected) == 10
    for frame, reference in zip(frames, expected, strict=True):
        np.testing.assert_array_equal(frame, reference)


def test_a_gpu_cuts_every_frame_when_kernels_run(monkeypatch):
    layers = _layers()
    cutter = _Cutter(layers)
    # WHY: replaces the kernel library's device, which CI runners do not have.
    monkeypatch.setattr(gpu_moves, "gpu_cutter", lambda _layers: cutter)

    frames = list(move_frames(layers, PARAMS))

    assert cutter.cuts == 10
    assert all(frame[0, 0, 0] == 7 for frame in frames)


@pytest.mark.parametrize("error", [RuntimeError, AssertionError, ValueError])
def test_a_gpu_failing_part_way_hands_the_rest_to_the_cpu(monkeypatch, error):
    layers = _layers()
    cutter = _Cutter(layers, fail_from=4, error=error)
    # WHY: replaces the kernel library's device, which CI runners do not have.
    monkeypatch.setattr(gpu_moves, "gpu_cutter", lambda _layers: cutter)

    frames = list(move_frames(layers, PARAMS))
    expected = list(ken_burns_frames(layers, PARAMS))

    assert len(frames) == 10
    assert [frame[0, 0, 0] == 7 for frame in frames] == [True] * 4 + [False] * 6
    for frame, reference in zip(frames[4:], expected[4:], strict=True):
        np.testing.assert_array_equal(frame, reference)
    assert cutter.closed


def test_a_float_picture_is_not_given_to_the_gpu():
    layers = _layers()
    layers = type(layers)(**{**layers.__dict__, "big": layers.big.astype(np.float32)})

    assert REAL_GPU_CUTTER(layers) is None


class _DeviceLog:
    """What a fake device saw: the thread of every call into it."""

    def __init__(self) -> None:
        self.threads: list[tuple[str, int]] = []
        self.released = threading.Event()


def _fake_kernel_library(monkeypatch, log: _DeviceLog, *, fail_on_upload: bool = False):
    """Stand in for the kernel library and a CUDA device, which CI runners do not have."""

    class FakeGpuFrameCutter:
        def __init__(self, layers) -> None:
            log.threads.append(("upload", threading.get_ident()))
            if fail_on_upload:
                raise AssertionError("CUDA_ERROR_INVALID_CONTEXT")
            self.layers = layers

        def cut(self, view):
            log.threads.append(("cut", threading.get_ident()))
            frame = cut_frame(self.layers, view)
            frame[0, 0, 0] = 7
            return frame

        def release(self) -> None:
            log.threads.append(("release", threading.get_ident()))
            log.released.set()

    def init_kernels() -> str:
        log.threads.append(("start", threading.get_ident()))
        return "CUDA"

    # WHY: the move kernels and the runtime start are the kernel library's device boundary.
    monkeypatch.setattr(
        gpu_moves, "_move_kernels", lambda: types.SimpleNamespace(GpuFrameCutter=FakeGpuFrameCutter)
    )
    kernels = types.ModuleType("immich_memories.titles.kernels")
    kernels.init_kernels = init_kernels  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "immich_memories.titles.kernels", kernels)
    monkeypatch.setattr(gpu_moves, "gpu_cutter", REAL_GPU_CUTTER)


def test_stills_prepared_on_several_threads_drive_the_device_from_one(monkeypatch):
    """#2785: on CUDA, a device call from any thread but the one that started it fails."""
    log = _DeviceLog()
    _fake_kernel_library(monkeypatch, log)
    layers = _layers()

    with ThreadPoolExecutor(2, thread_name_prefix="prepare") as pool:
        moves = list(pool.map(lambda _: list(move_frames(layers, PARAMS)), range(4)))
        preparing = set(pool.map(lambda _: threading.get_ident(), range(4)))

    assert all(len(frames) == 10 and frames[0][0, 0, 0] == 7 for frames in moves)
    device_threads = {thread for _call, thread in log.threads}
    assert len(device_threads) == 1
    assert not device_threads & preparing
    assert [call for call, _thread in log.threads].count("release") == 4


def test_a_still_the_gpu_cannot_take_is_cut_whole_on_the_cpu(monkeypatch, caplog):
    log = _DeviceLog()
    _fake_kernel_library(monkeypatch, log, fail_on_upload=True)
    layers = _layers()

    with caplog.at_level(logging.WARNING, logger="immich_memories.photos.gpu_moves"):
        frames = list(move_frames(layers, PARAMS))

    expected = list(ken_burns_frames(layers, PARAMS))
    assert len(frames) == len(expected) == 10
    for frame, reference in zip(frames, expected, strict=True):
        np.testing.assert_array_equal(frame, reference)
    assert "CUDA_ERROR_INVALID_CONTEXT" in caplog.text


def test_a_move_stopped_early_frees_its_device_buffers_on_the_kernel_thread(monkeypatch):
    log = _DeviceLog()
    _fake_kernel_library(monkeypatch, log)

    def first_frames():
        frames = move_frames(_layers(), PARAMS)
        next(frames)
        frames.close()

    worker = threading.Thread(target=first_frames)
    worker.start()
    worker.join()

    assert log.released.wait(5)
    started = dict(log.threads)["start"]
    assert dict(log.threads)["release"] == started != worker.ident
