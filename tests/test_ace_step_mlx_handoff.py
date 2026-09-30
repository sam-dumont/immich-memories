"""The owned adapter follows upstream lifecycle seams without global runtime changes."""

import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


def test_owned_initializer_keeps_main_weights_on_cpu_until_mlx_conversion(monkeypatch, tmp_path):
    from immich_memories.audio.generators.ace_step_mlx_handoff import install_mlx_memory_handoff

    events = []
    decoder = Mock()
    decoder.named_modules.return_value = []
    decoder.named_parameters.return_value = []
    model = Mock()
    model.decoder = decoder
    model.named_modules.return_value = []
    model.named_parameters.return_value = []
    handler = SimpleNamespace(
        model=None,
        device="mps",
        dtype="float32",
        offload_to_cpu=False,
        offload_dit_to_cpu=False,
        lora_loaded=False,
        use_lora=False,
        generate_music=lambda **_kwargs: "audio",
        _init_mlx_dit=lambda **_kwargs: False,
        _mlx_run_diffusion=lambda **_kwargs: None,
    )

    def load(*_args, **_kwargs):
        events.append((handler.offload_to_cpu, handler.offload_dit_to_cpu))
        handler.model = model
        return "loaded"

    handler._load_main_model_from_checkpoint = load
    # WHY: torch dtype/device transfer is native; the lifecycle seam itself remains real.
    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(
            bfloat16="bf16", mps=SimpleNamespace(synchronize=lambda: None, empty_cache=lambda: None)
        ),
    )
    (tmp_path / "model.safetensors").write_bytes(b"checkpoint")

    assert install_mlx_memory_handoff(handler, tmp_path / "model.safetensors")
    assert handler._load_main_model_from_checkpoint() == "loaded"
    assert events == [(True, True)]
    assert not handler.offload_to_cpu and not handler.offload_dit_to_cpu
    decoder.to.assert_called_once_with("meta")


def test_mlx_initialization_defers_native_weights_until_after_conditioning(monkeypatch, tmp_path):
    from contextlib import nullcontext

    from immich_memories.audio.generators import ace_step_mlx_handoff

    core = SimpleNamespace(
        get_active_memory=lambda: 0,
        bfloat16="bf16",
        synchronize=lambda: None,
        clear_cache=lambda: None,
    )
    monkeypatch.setitem(sys.modules, "mlx", SimpleNamespace(core=core))
    monkeypatch.setitem(sys.modules, "mlx.core", core)
    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(
            bfloat16="bf16",
            no_grad=nullcontext,
            mps=SimpleNamespace(synchronize=lambda: None, empty_cache=lambda: None),
        ),
    )
    native = Mock()
    native.parameters.return_value = {}
    monkeypatch.setitem(
        sys.modules,
        "acestep.models.mlx.dit_model",
        SimpleNamespace(MLXDiTDecoder=SimpleNamespace(from_config=lambda _config: native)),
    )
    converted = []
    monkeypatch.setattr(
        ace_step_mlx_handoff,
        "load_checkpoint_decoder",
        lambda checkpoint, decoder: converted.append((checkpoint, decoder)),
        raising=False,
    )
    model = Mock()
    model.named_modules.return_value = []
    model.named_parameters.return_value = []
    model.decoder.named_modules.return_value = []
    model.decoder.named_parameters.return_value = []
    conditioning = Mock()
    model.named_children.return_value = [("decoder", model.decoder), ("encoder", conditioning)]
    handler = SimpleNamespace(
        model=model,
        config=object(),
        device="mps",
        dtype="float32",
        offload_to_cpu=False,
        offload_dit_to_cpu=False,
        _load_main_model_from_checkpoint=lambda: None,
        generate_music=lambda **_kwargs: "audio",
        _init_mlx_dit=lambda **_kwargs: False,
        _mlx_run_diffusion=lambda **_kwargs: None,
    )
    silence = Mock()
    handler.silence_latent = silence
    (tmp_path / "model.safetensors").write_bytes(b"checkpoint")

    assert ace_step_mlx_handoff.install_mlx_memory_handoff(handler, tmp_path / "model.safetensors")
    handler._load_main_model_from_checkpoint()
    assert handler._init_mlx_dit(compile_model=False)

    assert converted == []
    assert isinstance(handler.mlx_decoder, ace_step_mlx_handoff._DeferredDecoder)
    assert handler.use_mlx_dit
    model.decoder.to.assert_any_call("meta")
    conditioning.to.assert_called_once_with(device="mps", dtype="float32")
    silence.to.assert_called_once_with(device="mps", dtype="float32")
    assert not any(call.args == ("meta",) for call in model.to.call_args_list)


def test_failed_conversion_cannot_move_weights_to_mps_when_budget_is_insufficient(
    monkeypatch, tmp_path
):
    import pytest

    from immich_memories.audio.generators import ace_step_mlx_handoff

    core = SimpleNamespace(
        get_active_memory=lambda: 0, synchronize=lambda: None, clear_cache=lambda: None
    )
    monkeypatch.setitem(sys.modules, "mlx", SimpleNamespace(core=core))
    monkeypatch.setitem(sys.modules, "mlx.core", core)
    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(
            bfloat16="bf16", mps=SimpleNamespace(synchronize=lambda: None, empty_cache=lambda: None)
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "acestep.models.mlx.dit_model",
        SimpleNamespace(MLXDiTDecoder=SimpleNamespace(from_config=lambda _config: Mock())),
    )

    def fail(*_args):
        raise RuntimeError("owned conversion failed")

    monkeypatch.setattr(ace_step_mlx_handoff, "load_checkpoint_decoder", fail)
    monkeypatch.setattr(ace_step_mlx_handoff, "available_memory_bytes", lambda: 0, raising=False)
    model = Mock()
    model.named_modules.return_value = []
    model.named_parameters.return_value = []
    model.decoder.named_modules.return_value = []
    model.decoder.named_parameters.return_value = []
    handler = SimpleNamespace(
        model=model,
        config=object(),
        device="mps",
        dtype="float32",
        offload_to_cpu=False,
        offload_dit_to_cpu=False,
        _load_main_model_from_checkpoint=lambda: None,
        generate_music=lambda **_kwargs: "audio",
        _init_mlx_dit=lambda **_kwargs: False,
        _mlx_run_diffusion=lambda **_kwargs: None,
    )
    checkpoint = tmp_path / "model.safetensors"
    checkpoint.write_bytes(b"checkpoint")
    ace_step_mlx_handoff.install_mlx_memory_handoff(handler, checkpoint)
    handler._load_main_model_from_checkpoint()

    owned = handler._init_mlx_dit.__self__
    owned.decoder_weights.park()
    with pytest.raises(RuntimeError, match="checkpoint loading failed"):
        owned.materialize_decoder()
    with pytest.raises(RuntimeError, match="fallback.*memory"):
        owned.fallback()
    model.to.assert_called_once_with("meta")


def test_diffusion_parks_conditioning_then_releases_decoder_before_vae(monkeypatch, tmp_path):
    from immich_memories.audio.generators.ace_step_mlx_handoff import _DeferredDecoder, _Handoff

    events = []
    active = [100]
    core = SimpleNamespace(
        get_active_memory=lambda: active[0],
        synchronize=lambda: events.append("mlx-sync"),
        clear_cache=lambda: events.append("mlx-cache"),
    )
    monkeypatch.setitem(sys.modules, "mlx", SimpleNamespace(core=core))
    monkeypatch.setitem(sys.modules, "mlx.core", core)
    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(
            mps=SimpleNamespace(
                synchronize=lambda: events.append("torch-sync"),
                empty_cache=lambda: events.append("torch-cache"),
            )
        ),
    )
    handler = SimpleNamespace(
        _load_main_model_from_checkpoint=lambda: None,
        generate_music=lambda **_kwargs: "audio",
        _init_mlx_dit=lambda: None,
        mlx_decoder=_DeferredDecoder(),
        text_encoder=Mock(),
    )

    def diffuse(*args, **kwargs):
        events.append("diffusion")
        assert handler.mlx_decoder is not None
        return "torch-latents"

    handler._mlx_run_diffusion = diffuse
    owned = _Handoff(handler, tmp_path / "model.safetensors")
    owned.weights = Mock()
    owned.weights.park.side_effect = lambda: events.append("park-conditioning")
    owned.native_bytes = 100

    def materialize():
        events.append("load-native-checkpoint")
        handler.mlx_decoder = object()

    owned.materialize_decoder = materialize

    def collect():
        active[0] = 0

    monkeypatch.setattr("immich_memories.audio.generators.ace_step_mlx_handoff.gc.collect", collect)

    assert owned.diffuse() == "torch-latents"
    assert (
        events.index("park-conditioning")
        < events.index("torch-cache")
        < events.index("load-native-checkpoint")
        < events.index("diffusion")
    )
    handler.text_encoder.to.assert_called_once_with("meta")
    assert handler.mlx_decoder is None


def test_retained_native_allocations_block_fallback_before_checkpoint_restore(
    monkeypatch, tmp_path
):
    import pytest

    from immich_memories.audio.generators.ace_step_mlx_handoff import _Handoff

    core = SimpleNamespace(
        get_active_memory=lambda: 4 * 1024**3, synchronize=lambda: None, clear_cache=lambda: None
    )
    monkeypatch.setitem(sys.modules, "mlx", SimpleNamespace(core=core))
    monkeypatch.setitem(sys.modules, "mlx.core", core)
    handler = SimpleNamespace(
        _load_main_model_from_checkpoint=lambda: None,
        generate_music=lambda **_kwargs: "audio",
        _init_mlx_dit=lambda: None,
        _mlx_run_diffusion=lambda: None,
        mlx_decoder=object(),
    )
    owned = _Handoff(handler, tmp_path / "model.safetensors")
    owned.weights = Mock()
    owned.native_bytes = 3 * 1024**3
    owned.torch_generate = Mock()

    with pytest.raises(RuntimeError, match="allocations remain live"):
        owned.fallback()
    owned.weights.restore.assert_not_called()
    owned.torch_generate.assert_not_called()


def test_owned_handler_rejects_a_second_job_before_touching_parked_models(tmp_path):
    import inspect

    import pytest

    from immich_memories.audio.generators.ace_step_mlx_handoff import install_mlx_memory_handoff

    def generate_music(caption: str):
        return caption

    handler = SimpleNamespace(
        generate_music=generate_music,
        _load_main_model_from_checkpoint=lambda: None,
        _init_mlx_dit=lambda: None,
        _mlx_run_diffusion=lambda: None,
    )
    assert install_mlx_memory_handoff(handler, tmp_path / "model.safetensors")
    assert inspect.signature(handler.generate_music) == inspect.signature(generate_music)
    assert handler.generate_music(caption="instrumental") == "instrumental"
    with pytest.raises(RuntimeError, match="one generation"):
        handler.generate_music(caption="second")


def test_runtime_installs_owned_adapter_before_initialization_without_second_bf16_copy(
    monkeypatch, tmp_path
):
    from immich_memories.audio.generators import ace_step_mlx_handoff, ace_step_runtime

    events = []
    handler = SimpleNamespace(
        initialize_service=lambda **_kwargs: (events.append("initialize") or "ready", True)
    )
    monkeypatch.setattr(
        ace_step_mlx_handoff,
        "install_mlx_memory_handoff",
        lambda value, path: events.append((value, path)) or True,
    )
    monkeypatch.setattr(
        ace_step_runtime, "_cast_mlx_decoder_to_bf16", lambda _value: events.append("second-copy")
    )
    checkpoint = tmp_path / "model.safetensors"

    assert (
        ace_step_runtime._initialize_dit_handler(
            lambda: handler,
            project_root=tmp_path,
            dit_model="acestep-v15-turbo",
            device="mps",
            offload=False,
            use_mlx_dit=True,
            owned_mlx_checkpoint=checkpoint,
        )
        is handler
    )
    assert events == [(handler, checkpoint), "initialize"]


def test_owned_diffusion_failure_drops_native_traceback_before_upstream_fallback(
    monkeypatch, tmp_path
):
    import weakref

    import pytest

    from immich_memories.audio.generators.ace_step_mlx_handoff import _Handoff

    references = []

    class NativeAllocation:
        def __init__(self, size):
            self.size = size
            references.append(weakref.ref(self))

    core = SimpleNamespace(
        get_active_memory=lambda: sum(ref().size for ref in references if ref() is not None),
        synchronize=lambda: None,
        clear_cache=lambda: None,
    )
    monkeypatch.setitem(sys.modules, "mlx", SimpleNamespace(core=core))
    monkeypatch.setitem(sys.modules, "mlx.core", core)
    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(mps=SimpleNamespace(synchronize=lambda: None, empty_cache=lambda: None)),
    )

    def native_failure():
        activation = NativeAllocation(1024**3)
        assert activation.size
        raise RuntimeError("owned native failure")

    handler = SimpleNamespace(
        _load_main_model_from_checkpoint=lambda: None,
        _init_mlx_dit=lambda: None,
        _mlx_run_diffusion=native_failure,
        mlx_decoder=NativeAllocation(3 * 1024**3),
    )
    owned = _Handoff(handler, tmp_path / "model.safetensors")
    owned.weights = Mock()
    owned.native_bytes = 3 * 1024**3

    with pytest.raises(RuntimeError, match="owned native failure") as failure:
        owned.diffuse()

    assert failure.value.__traceback__ is not None
    assert failure.value.__context__ is None
    assert all(ref() is None for ref in references)
    assert owned.native_bytes == 0


def test_partial_native_load_refusal_survives_upstream_fallback(monkeypatch, tmp_path):
    import pytest

    from immich_memories.audio.generators import ace_step_mlx_handoff

    active = [0]
    core = SimpleNamespace(
        get_active_memory=lambda: active[0], synchronize=lambda: None, clear_cache=lambda: None
    )
    monkeypatch.setitem(sys.modules, "mlx", SimpleNamespace(core=core))
    monkeypatch.setitem(sys.modules, "mlx.core", core)
    monkeypatch.setitem(
        sys.modules,
        "acestep.models.mlx.dit_model",
        SimpleNamespace(MLXDiTDecoder=SimpleNamespace(from_config=lambda _config: Mock())),
    )

    def partial_load(*_args):
        active[0] = 3 * 1024**3
        raise RuntimeError("native allocation remains externally referenced")

    monkeypatch.setattr(ace_step_mlx_handoff, "load_checkpoint_decoder", partial_load)
    handler = SimpleNamespace(
        config=object(),
        mlx_decoder=ace_step_mlx_handoff._DeferredDecoder(),
        _load_main_model_from_checkpoint=lambda: None,
        _init_mlx_dit=lambda: None,
        _mlx_run_diffusion=lambda: None,
    )
    owned = ace_step_mlx_handoff._Handoff(handler, tmp_path / "model.safetensors")
    owned.decoder_weights = Mock()
    owned.weights = Mock()
    owned.torch_generate = Mock()
    with pytest.raises(RuntimeError, match="allocations remain live"):
        owned.materialize_decoder()
    with pytest.raises(RuntimeError, match="allocations remain live"):
        owned.fallback()
    owned.weights.restore.assert_not_called()
    owned.torch_generate.assert_not_called()


@pytest.mark.parametrize("failure", [None, KeyboardInterrupt])
def test_torch_fallback_releases_restored_weights_before_vae(monkeypatch, tmp_path, failure):
    from immich_memories.audio.generators.ace_step_mlx_handoff import _Handoff

    events = []
    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(
            mps=SimpleNamespace(
                synchronize=lambda: events.append("sync"),
                empty_cache=lambda: events.append("cache"),
            )
        ),
    )
    handler = SimpleNamespace(
        _load_main_model_from_checkpoint=lambda: None,
        _init_mlx_dit=lambda: None,
        _mlx_run_diffusion=lambda: None,
        mlx_decoder=None,
    )
    owned = _Handoff(handler, tmp_path / "model.safetensors")
    owned.weights = SimpleNamespace(park=lambda: events.append("park"))
    owned.restore_initial = lambda: events.append("restore")

    def generate():
        events.append("generate")
        if failure is not None:
            raise failure("owned cancellation")
        return "latents"

    owned.torch_generate = generate
    if failure is None:
        assert owned.fallback() == "latents"
    else:
        with pytest.raises(failure, match="owned cancellation"):
            owned.fallback()
    assert events == ["restore", "generate", "park", "sync", "cache"]
