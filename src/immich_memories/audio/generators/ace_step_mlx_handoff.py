"""Own ACE-Step's sequential Torch conditioning and MLX diffusion weight lifetimes."""

import gc
import logging
import os
import traceback
from functools import wraps
from pathlib import Path
from typing import Any

from immich_memories.audio.generators.ace_step_mlx_convert import load_checkpoint_decoder
from immich_memories.audio.generators.ace_step_mlx_weights import ParkedWeights
from immich_memories.audio.generators.memory_budget import available_memory_bytes

logger = logging.getLogger(__name__)


class _DeferredDecoder:
    """Keep upstream's native route selected without allocating decoder weights."""

    @staticmethod
    def parameters() -> dict[str, Any]:
        return {}


class _Handoff:
    def __init__(self, handler: Any, checkpoint: Path) -> None:
        self.handler, self.checkpoint = handler, checkpoint
        self.weights: ParkedWeights | None = None
        self.decoder_weights: ParkedWeights | None = None
        self.load = handler._load_main_model_from_checkpoint
        self.initialize = handler._init_mlx_dit
        self.diffusion = handler._mlx_run_diffusion
        self.native_bytes = 0
        self.torch_generate = None

    def load_main(self, *args: Any, **kwargs: Any) -> Any:
        if self.handler.device != "mps":
            return self.load(*args, **kwargs)
        previous = self.handler.offload_to_cpu, self.handler.offload_dit_to_cpu
        self.handler.offload_to_cpu = self.handler.offload_dit_to_cpu = True
        try:
            result = self.load(*args, **kwargs)
        finally:
            self.handler.offload_to_cpu, self.handler.offload_dit_to_cpu = previous
        self.weights = ParkedWeights(self.handler.model)
        self.decoder_weights = ParkedWeights(self.handler.model.decoder)
        self.torch_generate = self.handler.model.generate_audio
        self.handler.model.generate_audio = self.fallback
        # Native diffusion reloads directly from the BF16 checkpoint after
        # conditioning; keep no inactive CPU decoder copy during that phase.
        self.decoder_weights.park()
        return result

    def initialize_mlx(self, compile_model: bool = False) -> bool:
        if self.weights is None or self.decoder_weights is None:
            return self.initialize(compile_model=compile_model)
        if compile_model:
            self.restore_initial()
            return self.initialize(compile_model=compile_model)
        self.handler.mlx_decoder = _DeferredDecoder()
        self.handler.use_mlx_dit = True
        self.handler.mlx_dit_compiled = False
        self.move_conditioning()
        return True

    def materialize_decoder(self) -> None:
        import mlx.core as mx  # type: ignore[import-not-found]
        from acestep.models.mlx.dit_model import MLXDiTDecoder

        assert self.decoder_weights is not None
        native = None
        baseline = mx.get_active_memory()
        try:
            native = MLXDiTDecoder.from_config(self.handler.config)
            load_checkpoint_decoder(self.checkpoint, native)
            native.materialize_static_buffers()
        except Exception as exc:
            logger.warning("Owned MLX conversion failed; restoring Torch: %s", str(exc))
            traceback.clear_frames(exc.__traceback__)
            exc.__traceback__ = None
            native = None
        if native is None:
            self.handler.mlx_decoder = None
            self.handler.use_mlx_dit = False
            gc.collect()
            mx.synchronize()
            mx.clear_cache()
            remaining = mx.get_active_memory() - baseline
            if remaining > 1024**2:
                self.native_bytes = remaining
                raise RuntimeError(
                    "Owned MLX conversion allocations remain live; refusing Torch restoration"
                )
            raise RuntimeError("Owned MLX checkpoint loading failed")
        self.native_bytes = self.decoder_weights.parameter_bytes // 2
        self.handler.mlx_decoder = native
        self.handler.use_mlx_dit = True
        self.handler.mlx_dit_compiled = False

    def move_conditioning(self) -> None:
        import torch

        for name, module in self.handler.model.named_children():
            if name != "decoder":
                module.to(device=self.handler.device, dtype=self.handler.dtype)
        with torch.no_grad():
            parameter = self.handler.model.null_condition_emb
            parameter.data = parameter.data.to(device=self.handler.device, dtype=self.handler.dtype)
        silence = getattr(self.handler, "silence_latent", None)
        if silence is not None:
            self.handler.silence_latent = silence.to(
                device=self.handler.device, dtype=self.handler.dtype
            )
        torch.mps.synchronize()
        torch.mps.empty_cache()

    def restore_initial(self) -> None:
        assert self.weights is not None
        # Conversion can fail after individual decoder tensors have become meta.
        # Restore the complete checkpoint namespace, never move a partial meta model.
        self.weights.park()
        import torch

        gc.collect()
        torch.mps.synchronize()
        torch.mps.empty_cache()
        self.require_fallback_memory(self.weights.parameter_bytes)
        self.weights.restore(self.checkpoint, self.handler.device)
        silence = getattr(self.handler, "silence_latent", None)
        if silence is not None:
            self.handler.silence_latent = silence.to(
                device=self.handler.device, dtype=self.handler.dtype
            )

    def diffuse(self, *args: Any, **kwargs: Any) -> Any:
        import torch

        assert self.weights is not None
        null = kwargs.get("null_condition_emb")
        if null is not None:
            kwargs["null_condition_emb"] = null.detach().clone()
        self.weights.park()
        text = getattr(self.handler, "text_encoder", None)
        if text is not None:
            text.to("meta")
        torch.mps.synchronize()
        torch.mps.empty_cache()
        failure = None
        result = None
        try:
            if isinstance(self.handler.mlx_decoder, _DeferredDecoder):
                self.materialize_decoder()
            result = self.diffusion(*args, **kwargs)
        except Exception as exc:
            # Clear only this owned failure, before upstream attempts Torch fallback.
            failure = str(exc)
            traceback.clear_frames(exc.__traceback__)
            exc.__traceback__ = None
        finally:
            self.release_decoder()
        if failure is not None:
            raise RuntimeError(f"Owned MLX diffusion failed: {failure}") from None
        return result

    def release_decoder(self) -> None:
        import mlx.core as mx

        before = mx.get_active_memory()
        self.handler.mlx_decoder = None
        self.handler.use_mlx_dit = False
        gc.collect()
        mx.synchronize()
        mx.clear_cache()
        after = mx.get_active_memory()
        if before - after < self.native_bytes - 1024**2:
            raise RuntimeError(
                "Owned MLX decoder allocations remain live; refusing Torch restoration"
            )
        self.native_bytes = 0

    def fallback(self, *args: Any, **kwargs: Any) -> Any:
        assert self.torch_generate is not None
        if self.native_bytes or getattr(self.handler, "mlx_decoder", None) is not None:
            self.release_decoder()
        self.restore_initial()
        try:
            return self.torch_generate(*args, **kwargs)
        finally:
            assert self.weights is not None
            self.weights.park()
            import torch

            torch.mps.synchronize()
            torch.mps.empty_cache()

    def require_fallback_memory(self, weight_bytes: int) -> None:
        available = available_memory_bytes()
        required = weight_bytes + 2 * 1024**3
        if available is None or available < required:
            raise RuntimeError(
                f"Owned Torch fallback has insufficient memory: needs {required} bytes "
                f"including an activation reserve; available={available}"
            )


def install_mlx_memory_handoff(handler: Any, checkpoint: Path) -> bool:
    """Attach only to the owned, pinned, uncompiled local MPS handler lifecycle."""
    seams = (
        "_load_main_model_from_checkpoint",
        "_init_mlx_dit",
        "_mlx_run_diffusion",
        "generate_music",
    )
    if os.environ.get("IMMICH_MEMORIES_ACESTEP_MLX_DIT_FP32") == "1":
        return False
    if not all(callable(getattr(handler, name, None)) for name in seams):
        return False
    if getattr(handler, "lora_loaded", False) or getattr(handler, "use_lora", False):
        return False
    handoff = _Handoff(handler, checkpoint)
    original_generate = handler.generate_music
    started = False

    @wraps(original_generate)
    def generate_once(*args: Any, **kwargs: Any) -> Any:
        nonlocal started
        if started:
            raise RuntimeError("Owned MLX handlers support one generation per child process")
        started = True
        return original_generate(*args, **kwargs)

    handler.generate_music = generate_once
    handler._load_main_model_from_checkpoint = handoff.load_main
    handler._init_mlx_dit = handoff.initialize_mlx
    handler._mlx_run_diffusion = handoff.diffuse
    return True
