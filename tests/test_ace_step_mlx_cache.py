"""The owned MLX allocator must not retain gigabytes of idle buffers on a 16 GiB Mac."""

import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize(
    ("physical_gib", "expected"), [(16, 0), (8, 0), (0, 0), (32, 4 * 1024**3), (128, 4 * 1024**3)]
)
def test_cache_budget_preserves_decode_context_and_scales_with_physical_ram(
    monkeypatch, physical_gib, expected
):
    from immich_memories.audio.generators import ace_step_runtime

    limit = Mock()
    core = SimpleNamespace(set_cache_limit=limit)
    monkeypatch.setitem(sys.modules, "mlx", SimpleNamespace(core=core))
    monkeypatch.setitem(sys.modules, "mlx.core", core)
    monkeypatch.setattr(
        ace_step_runtime, "_physical_memory_gb", lambda: physical_gib, raising=False
    )
    monkeypatch.delenv("ACESTEP_MLX_VAE_CHUNK", raising=False)
    assert ace_step_runtime._bound_mlx_memory() is None
    limit.assert_called_once_with(expected)
