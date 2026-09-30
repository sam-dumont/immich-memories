"""An owned MLX job can park Torch weights without losing rotary state."""

from types import SimpleNamespace
from unittest.mock import Mock


def test_parking_weights_preserves_nonpersistent_rotary_buffer_aliases():
    from immich_memories.audio.generators.ace_step_mlx_weights import ParkedWeights

    original = Mock()
    original.numel.return_value = 64
    original.element_size.return_value = 4
    saved = Mock()
    original.detach.return_value.cpu.return_value.clone.return_value = saved
    rotary = SimpleNamespace(_buffers={"inv_freq": original}, original_inv_freq=original)
    model = Mock()
    model.named_modules.return_value = [("rotary", rotary)]
    model.named_parameters.return_value = []
    parked_buffer = Mock()

    def park(_device):
        rotary._buffers["inv_freq"] = parked_buffer
        return model

    model.to.side_effect = park

    weights = ParkedWeights(model)
    weights.park()

    assert rotary.original_inv_freq is rotary._buffers["inv_freq"]
    weights.restore_buffers("mps")
    assert rotary.original_inv_freq is rotary._buffers["inv_freq"]
    assert rotary._buffers["inv_freq"] is saved.to.return_value


def test_failed_checkpoint_restore_releases_partial_native_weights(monkeypatch, tmp_path):
    import gc
    import sys
    import weakref
    from contextlib import nullcontext

    import pytest

    from immich_memories.audio.generators.ace_step_mlx_weights import ParkedWeights

    class NativeWeight:
        def copy_(self, _value):
            return None

    refs = []
    live = {}
    model = Mock()
    model.named_modules.return_value = []
    model.named_parameters.return_value = []
    model.state_dict.side_effect = lambda: live.copy()

    def allocate(**_kwargs):
        for name in ("first", "second"):
            live[name] = NativeWeight()
            refs.append(weakref.ref(live[name]))

    def move(*args, **_kwargs):
        if args == ("meta",):
            live.clear()
        return model

    model.to.side_effect = move
    model.to_empty.side_effect = allocate

    class Checkpoint:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def keys(self):
            return ["first", "second"]

        def get_tensor(self, name):
            if name == "second":
                raise RuntimeError("incomplete checkpoint")
            return object()

    # WHY: replace only native allocation/checkpoint APIs, preserving actual exception ownership.
    synced = []
    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(
            no_grad=nullcontext, mps=SimpleNamespace(synchronize=lambda: synced.append(True))
        ),
    )
    monkeypatch.setitem(
        sys.modules, "safetensors", SimpleNamespace(safe_open=lambda *_a, **_kw: Checkpoint())
    )
    weights = ParkedWeights(model)
    with pytest.raises(RuntimeError, match="incomplete checkpoint") as failure:
        weights.restore(tmp_path / "weights.safetensors", "mps")
    assert failure.value.__traceback__ is not None
    gc.collect()
    assert synced == [True]
    assert not live
    assert all(reference() is None for reference in refs)


def test_tied_weight_layout_is_rejected_before_incremental_parking():
    import pytest

    from immich_memories.audio.generators.ace_step_mlx_weights import ParkedWeights

    parameter = Mock(dtype="fp32")
    parameter.numel.return_value = 1
    parameter.element_size.return_value = 4
    model = Mock()
    model.named_parameters.return_value = [("first", parameter), ("alias", parameter)]
    with pytest.raises(ValueError, match="Tied Torch"):
        ParkedWeights(model)


def test_pinned_immutable_fsq_codebook_keeps_one_cpu_owner_across_parking():
    from immich_memories.audio.generators.ace_step_mlx_weights import ParkedWeights

    class FSQ:
        __module__ = "vector_quantize_pytorch.finite_scalar_quantization"

    value = Mock(shape=(64000, 6), dtype="torch.float32")
    value.numel.return_value = 64000 * 6
    value.element_size.return_value = 4
    module = FSQ()
    module._buffers = {"implicit_codebook": value}
    module._non_persistent_buffers_set = {"implicit_codebook"}
    model = Mock()
    model.named_parameters.return_value = []
    model.named_modules.return_value = [("tokenizer.quantizer.layers.0", module)]

    weights = ParkedWeights(model)
    assert weights.buffers[0].value is value.detach.return_value.cpu.return_value
    value.detach.return_value.cpu.return_value.clone.assert_not_called()
    weights.park()
    weights.restore_buffers("mps")
    assert module._buffers["implicit_codebook"] is weights.buffers[0].value.to.return_value


def test_unknown_large_buffer_remains_rejected():
    import pytest

    from immich_memories.audio.generators.ace_step_mlx_weights import ParkedWeights

    value = Mock()
    value.numel.return_value = 64000 * 6
    value.element_size.return_value = 4
    module = SimpleNamespace(_buffers={"implicit_codebook": value})
    model = Mock()
    model.named_parameters.return_value = []
    model.named_modules.return_value = [("unknown", module)]
    with pytest.raises(ValueError, match="Large Torch buffers"):
        ParkedWeights(model)
