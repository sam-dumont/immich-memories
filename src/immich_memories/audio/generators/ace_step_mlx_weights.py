"""Park checkpoint-backed Torch modules while an owned MLX phase runs."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class _Buffer:
    module: Any
    name: str
    value: Any
    aliases: tuple[str, ...]


def _snapshot_buffer(module: Any, name: str, value: Any) -> Any:
    # Pinned FSQ constructs this immutable grid once; it is not in the checkpoint.
    # Retain its existing CPU storage, rather than a second native or cloned copy.
    codebook = (
        type(module).__module__ == "vector_quantize_pytorch.finite_scalar_quantization"
        and type(module).__name__ == "FSQ"
        and name == "implicit_codebook"
        and name in module._non_persistent_buffers_set
        and tuple(value.shape) == (64000, 6)
        and str(value.dtype) == "torch.float32"
    )
    if value.numel() * value.element_size() > 1024**2 and not codebook:
        raise ValueError("Large Torch buffers are not supported by the MLX handoff")
    cpu = value.detach().cpu()
    return cpu if codebook else cpu.clone()


class ParkedWeights:
    """Keep architecture and small rotary state, not a second native weight copy."""

    def __init__(self, model: Any) -> None:
        self.model = model
        self.buffers = []
        self.parameter_bytes = 0
        self.dtype = None
        seen = set()
        for _, value in model.named_parameters(remove_duplicate=False):
            if id(value) in seen:
                raise ValueError("Tied Torch parameters are not supported by the MLX handoff")
            seen.add(id(value))
            self.parameter_bytes += value.numel() * value.element_size()
            if self.dtype is not None and value.dtype != self.dtype:
                raise ValueError("Mixed Torch weight precision is not supported by the MLX handoff")
            self.dtype = value.dtype
        for _, module in model.named_modules():
            for name, value in module._buffers.items():
                if value is None:
                    continue
                aliases = tuple(key for key, item in vars(module).items() if item is value)
                self.buffers.append(
                    _Buffer(module, name, _snapshot_buffer(module, name, value), aliases)
                )

    def _assign_buffer(self, buffer: _Buffer, value: Any) -> None:
        buffer.module._buffers[buffer.name] = value
        for alias in buffer.aliases:
            setattr(buffer.module, alias, value)

    def park(self) -> None:
        """Drop native storage and repair nonpersistent buffer aliases on the meta module."""
        self.model.to("meta")
        for buffer in self.buffers:
            self._assign_buffer(buffer, buffer.module._buffers[buffer.name])

    def restore_buffers(self, device: str) -> None:
        for buffer in self.buffers:
            self._assign_buffer(buffer, buffer.value.to(device))

    def restore(self, checkpoint: Path, device: str) -> None:
        """Stream one checkpoint tensor at a time; failed loads leave no partial native model."""
        import torch
        from safetensors import safe_open  # type: ignore[import-not-found]

        state = {}
        destination = None
        try:
            self.model.to(dtype=self.dtype)
            self.model.to_empty(device=device)
            state = self.model.state_dict()
            with safe_open(checkpoint, framework="pt", device="cpu") as source, torch.no_grad():
                if set(state) - set(source.keys()):
                    raise ValueError("The MLX fallback checkpoint does not cover the Torch model")
                for name, destination in state.items():
                    destination.copy_(source.get_tensor(name))
                    if device == "mps":
                        torch.mps.synchronize()
            self.restore_buffers(device)
        except BaseException:
            # A raised exception retains this frame; leave no detached native state in it.
            state.clear()
            destination = None
            self.park()
            raise
