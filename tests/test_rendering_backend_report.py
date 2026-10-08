"""The log has to distinguish a GPU from the kernel library's CPU fallback.

init_kernels() returns the string "CPU" when Metal, CUDA and Vulkan all fail
to start. The service logged "GPU rendering enabled: CPU", so a container
rendering titles on the processor looked identical to one using the card —
and titles are the most expensive stage in the pipeline.
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from immich_memories.titles.rendering_service import KernelRenderer, RenderingService


@pytest.fixture
def config() -> MagicMock:
    cfg = MagicMock()
    cfg.use_gpu_rendering = True
    return cfg


def _renderer_reporting(backend: str | None) -> KernelRenderer:
    """A loaded kernel renderer whose init_kernels() answers with `backend`."""
    return KernelRenderer(
        create_video=lambda *args, **kwargs: Path("unused"),  # noqa: ARG005
        config_type=MagicMock,
        init_kernels=lambda: backend,
    )


@pytest.mark.parametrize("backend", ["Metal", "CUDA", "Vulkan"])
def test_a_real_gpu_is_reported_as_one(backend: str, config, caplog) -> None:
    # WHY: loading the kernel renderer is the boundary — it claims a GPU and, on
    # a processor without AVX, kills the interpreter. This asserts the log line.
    with (
        patch(
            "immich_memories.titles.rendering_service.load_kernel_renderer",
            return_value=_renderer_reporting(backend),
        ),
        caplog.at_level(logging.INFO),
    ):
        service = RenderingService(config)

    assert service.backend == backend
    assert f"on GPU: {backend}" in caplog.text
    assert "CPU" not in caplog.text


def test_the_cpu_fallback_says_so_and_warns(config, caplog) -> None:
    # WHY: same boundary; a machine with working Metal can never reach this case.
    with (
        patch(
            "immich_memories.titles.rendering_service.load_kernel_renderer",
            return_value=_renderer_reporting("CPU"),
        ),
        caplog.at_level(logging.INFO),
    ):
        service = RenderingService(config)

    assert not service.use_gpu, "CPU titles animate raster text through FFmpeg"
    assert service.backend == "CPU"
    assert "on CPU" in caplog.text
    assert any(r.levelno == logging.WARNING for r in caplog.records), (
        "a silent CPU fallback is the bug"
    )


def test_a_cpu_that_cannot_run_a_kernel_falls_to_pil_with_its_reason(config, caplog) -> None:
    """The no-AVX case (#910): no renderer is loaded at all, and the log says why.

    "Kernel library unavailable" on its own sent a NAS user looking for a missing
    package that was installed and imported fine. Nothing is patched at the
    rendering-service boundary here: the real `load_kernel_renderer` has to
    answer None off the probe alone, without reaching the import behind it.
    """
    crash = (
        "kernel backend crashed on this CPU: illegal instruction; "
        "titles fall back to the PIL renderer"
    )
    # WHY: the probe spawns a child interpreter; this is the answer a Celeron J4125 gives.
    with (
        patch(
            "immich_memories.titles.kernel_backend_probe.kernel_dispatch_failure",
            return_value=crash,
        ),
        caplog.at_level(logging.INFO),
    ):
        service = RenderingService(config)

    assert not service.use_gpu
    assert service.backend is None
    assert "illegal instruction" in caplog.text


def _cpu_fallback_logged_during(tier: str | None, config, caplog) -> list[logging.LogRecord]:
    from immich_memories.tracking.timing import collecting

    with (
        # WHY: same boundary as above; the kernel library is not loaded in a unit test.
        patch(
            "immich_memories.titles.rendering_service.load_kernel_renderer",
            return_value=_renderer_reporting("CPU"),
        ),
        collecting() as collected,
        caplog.at_level(logging.INFO),
    ):
        if tier:
            collected.diagnostics["tier"] = tier
        RenderingService(config)
    return [r for r in caplog.records if "on CPU" in r.getMessage()]


def test_cpu_titles_on_the_basic_tier_are_info_not_a_warning(config, caplog) -> None:
    records = _cpu_fallback_logged_during("basic", config, caplog)

    assert [r.levelno for r in records] == [logging.INFO]


def test_cpu_titles_on_a_gpu_tier_still_warn(config, caplog) -> None:
    records = _cpu_fallback_logged_during("gpu", config, caplog)

    assert [r.levelno for r in records] == [logging.WARNING]


def test_host_without_gpu_never_compiles_title_kernels(config, caplog):
    with (
        # WHY: a CPU-only host can pass the native CPU safety probe.
        patch(
            "immich_memories.titles.kernel_backend_probe.kernel_dispatch_failure", return_value=None
        ),
        # WHY: cached driver probes report that no GPU can dispatch here.
        patch(
            "immich_memories.titles.kernel_backend_probe.gpu_backend",
            return_value=(None, ("CUDA: found no device", "Vulkan: found no device")),
        ),
        # WHY: native title compilation must never start on this host.
        patch(
            "immich_memories.titles.renderer_kernels.init_kernels",
            side_effect=AssertionError("CPU-only title kernels must not compile"),
        ),
        caplog.at_level(logging.INFO),
    ):
        service = RenderingService(config)

    assert not service.use_gpu
    assert "using FFmpeg animated titles with raster text" in caplog.text
    assert "found no device" in caplog.text


def test_system_report_on_cpu_host_does_not_compile_title_kernels():
    from immich_memories.tracking.system_info import capture_system_info

    with (
        # WHY: a CPU-only host can pass the native CPU safety probe.
        patch(
            "immich_memories.titles.kernel_backend_probe.kernel_dispatch_failure", return_value=None
        ),
        # WHY: native GPU probes find no usable device.
        patch("immich_memories.titles.kernel_backend_probe.gpu_backend", return_value=(None, ())),
        # WHY: collecting diagnostics must not compile native title kernels.
        patch(
            "immich_memories.titles.kernels.init_kernels",
            side_effect=AssertionError("System reports must not compile title kernels"),
        ),
    ):
        assert not capture_system_info().gpu_kernels_available
