"""The owned converter evaluates only final BF16 arrays, one checkpoint tensor at a time."""

import sys
from types import SimpleNamespace


def test_checkpoint_loading_reads_only_decoder_tensors_one_at_a_time(monkeypatch, tmp_path):
    from contextlib import nullcontext

    from immich_memories.audio.generators.ace_step_mlx_convert import load_checkpoint_decoder

    visited = []
    loaded = []

    class Array:
        def astype(self, dtype):
            return self

    checkpoint = SimpleNamespace(
        keys=lambda: ["encoder.weight", "decoder.first", "decoder.second"],
        get_tensor=lambda name: visited.append(name) or name,
    )
    monkeypatch.setitem(
        sys.modules,
        "safetensors",
        SimpleNamespace(safe_open=lambda *_args, **_kwargs: nullcontext(checkpoint)),
    )
    monkeypatch.setitem(
        sys.modules,
        "acestep.models.mlx.dit_convert",
        SimpleNamespace(
            convert_decoder_weights=lambda model: [
                (name, Array()) for name in model.decoder.state_dict()
            ]
        ),
    )
    core = SimpleNamespace(bfloat16="bf16", eval=lambda _value: None, clear_cache=lambda: None)
    monkeypatch.setitem(sys.modules, "mlx", SimpleNamespace(core=core))
    monkeypatch.setitem(sys.modules, "mlx.core", core)
    native = SimpleNamespace(
        load_weights=lambda rows, **_kwargs: loaded.extend(name for name, _ in rows),
        parameters=lambda: [],
    )
    load_checkpoint_decoder(tmp_path / "model.safetensors", native)
    assert visited == ["decoder.first", "decoder.second"]
    assert loaded == ["first", "second"]
