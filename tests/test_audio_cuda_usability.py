"""Automatic local audio device selection needs a CUDA kernel that actually runs."""

import sys
import weakref
from types import ModuleType, SimpleNamespace

import pytest

from immich_memories.audio.generators.ace_step_runtime import build_v15_runtime
from immich_memories.audio.generators.demucs_local import DemucsLocalBackend
from tests.test_ace_step_backend import TestACEStepBackendV15Library as AceStepFixture


def _torch_with_kernel_failure():
    torch = ModuleType("torch")
    torch.backends = SimpleNamespace(mps=SimpleNamespace(is_available=lambda: False))
    torch.cuda = SimpleNamespace(is_available=lambda: True, synchronize=lambda: None)

    def unsupported_kernel(*args, **kwargs):
        raise RuntimeError("CUDA error: no kernel image is available for execution on the device")

    torch.ones = unsupported_kernel
    return torch


@pytest.mark.asyncio
async def test_demucs_auto_device_uses_cpu_when_cuda_has_no_usable_kernel(monkeypatch):
    # WHY: the CUDA runtime is the hardware boundary; no unsupported GPU model is loaded.
    monkeypatch.setitem(sys.modules, "torch", _torch_with_kernel_failure())

    health = await DemucsLocalBackend().health_check()

    assert health["device"] == "cpu"


def _working_torch(events, *, sync_fails=False):
    torch = _torch_with_kernel_failure()

    class Tensor:
        def add_(self, value):
            events.append(("kernel", value))

    def ones(size, *, device):
        events.append(("allocate", size, device))
        tensor = Tensor()
        events.append(weakref.ref(tensor))
        return tensor

    def synchronize():
        events.append("synchronize")
        if sync_fails:
            raise RuntimeError("CUDA asynchronous kernel failure")

    torch.ones = ones
    torch.cuda.synchronize = synchronize
    return torch


@pytest.mark.asyncio
@pytest.mark.parametrize("sync_fails, expected", [(False, "cuda"), (True, "cpu")])
async def test_demucs_requires_kernel_and_sync_without_retaining_tensor(
    monkeypatch, sync_fails, expected
):
    events = []
    # WHY: fake CUDA isolates hardware execution and lets tensor lifetime be checked.
    monkeypatch.setitem(sys.modules, "torch", _working_torch(events, sync_fails=sync_fails))

    health = await DemucsLocalBackend().health_check()

    assert health["device"] == expected
    assert events[0] == ("allocate", 1, "cuda")
    assert events[2:] == [("kernel", 1), "synchronize"]
    assert events[1]() is None


@pytest.mark.asyncio
async def test_explicit_demucs_device_does_not_probe_cuda(monkeypatch):
    events = []
    # WHY: hardware boundary records whether explicit selection bypasses auto detection.
    monkeypatch.setitem(sys.modules, "torch", _working_torch(events))

    health = await DemucsLocalBackend(device="cuda").health_check()

    assert health["device"] == "cuda"
    assert events == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mps, expected", [(False, "cpu"), (True, "mps")])
async def test_demucs_preserves_mps_and_handles_absent_cuda(monkeypatch, mps, expected):
    events = []
    torch = _working_torch(events)
    torch.cuda.is_available = lambda: False
    torch.backends.mps.is_available = lambda: mps
    # WHY: replace hardware availability without executing any real kernels.
    monkeypatch.setitem(sys.modules, "torch", torch)

    health = await DemucsLocalBackend().health_check()

    assert health["device"] == expected
    assert events == []


@pytest.mark.parametrize("usable, device, backend", [(False, "cpu", "pt"), (True, "cuda", "vllm")])
def test_ace_routes_both_handlers_using_cuda_execution(
    monkeypatch, tmp_path, usable, device, backend
):
    captured = {}
    modules, _ = AceStepFixture._fake_v15_modules(tmp_path, captured)
    # WHY: replace the optional ACE library, hardware, and available host memory.
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    torch = _working_torch([]) if usable else _torch_with_kernel_failure()
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr(
        "immich_memories.audio.generators.memory_budget.available_memory_bytes",
        lambda: 512 * 1024**3,
    )
    monkeypatch.setenv("ACESTEP_CHECKPOINTS_DIR", str(tmp_path / "checkpoints"))

    build_v15_runtime(
        model_variant="base",
        lm_model_size="1.7B",
        use_lm=True,
        disable_offload=False,
        cpu_offload=False,
    )

    assert captured["dit_init"]["device"] == device
    assert captured["lm_init"]["device"] == device
    assert captured["lm_init"]["backend"] == backend


def test_ace_cpu_fallback_still_checks_memory_before_loading(monkeypatch, tmp_path):
    captured = {}
    modules, _ = AceStepFixture._fake_v15_modules(tmp_path, captured)
    # WHY: replace optional ACE, host hardware, and host memory at their boundaries.
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setitem(sys.modules, "torch", _torch_with_kernel_failure())
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr(
        "immich_memories.audio.generators.memory_budget.available_memory_bytes", lambda: 0
    )
    monkeypatch.setenv("ACESTEP_CHECKPOINTS_DIR", str(tmp_path / "checkpoints"))

    with pytest.raises(RuntimeError, match="needs at least"):
        build_v15_runtime(
            model_variant="base",
            lm_model_size="1.7B",
            use_lm=True,
            disable_offload=False,
            cpu_offload=False,
        )

    assert "dit_init" not in captured
