"""Use the upstream decoder mapping without accumulating its temporary FP32 arrays."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any


def load_checkpoint_decoder(checkpoint: Path, decoder: Any) -> None:
    """Materialize native weights only after Torch conditioning weights are parked."""
    import mlx.core as mx  # type: ignore[import-not-found]
    from acestep.models.mlx.dit_convert import convert_decoder_weights
    from safetensors import safe_open  # type: ignore[import-not-found]

    with safe_open(checkpoint, framework="pt", device="cpu") as weights:
        keys = weights.keys()
        names = [name for name in keys if name.startswith("decoder.")]
        if not names:
            raise ValueError("Owned checkpoint has no decoder tensors")
        for full_name in names:
            name = full_name.removeprefix("decoder.")
            tensor = weights.get_tensor(full_name)
            source: Any = SimpleNamespace(
                decoder=SimpleNamespace(state_dict=lambda name=name, tensor=tensor: {name: tensor})
            )
            converted = convert_decoder_weights(source)
            for key, value in converted:
                final = value.astype(mx.bfloat16)
                mx.eval(final)
                decoder.load_weights([(key, final)], strict=False)
            converted.clear()
            value = tensor = source = None
            mx.clear_cache()
    mx.eval(decoder.parameters())
