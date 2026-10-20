"""Which ACE-Step DiT a render loads when the config says `auto`.

The 4B XL turbo model sounds brighter and degenerates less often than the 2B turbo model,
but it needs about twice the memory. `auto` takes XL where the host has room for it: a Mac
with 64 GB or more of unified memory, or an NVIDIA GPU with 16 GB or more. A host below
that does not load the 2B model: `ace_step_music_path` sends its films to the bundled
library, and an XL load that fails ends there too. A variant written in the config is used
as written.
"""

from __future__ import annotations

import platform
from dataclasses import dataclass

AUTO_VARIANT = "auto"
XL_VARIANT = "xl-turbo"
BASE_VARIANT = "turbo"

_XL_UNIFIED_MEMORY_GIB = 64.0
# A card sold as 16 GB reports 15.6-16 GiB once the driver keeps its share.
_XL_GPU_MEMORY_GIB = 15.5


@dataclass(frozen=True)
class HostMemory:
    """Total memory the music models can use: unified on Apple Silicon, else GPU VRAM."""

    unified_gib: float | None = None
    gpu_gib: float | None = None


def choose_model_variant(configured: str, host: HostMemory) -> str:
    """The variant to load: the configured one, or for `auto` the one this host holds."""
    if configured.strip().lower() != AUTO_VARIANT:
        return configured
    return XL_VARIANT if xl_fits(host) else BASE_VARIANT


def is_xl(variant: str) -> bool:
    """Whether a variant or DiT model name is one of the 4B XL models."""
    return "xl" in variant.strip().lower()


def xl_fits(host: HostMemory) -> bool:
    """Whether this host has the memory the XL model needs."""
    return (host.unified_gib or 0.0) >= _XL_UNIFIED_MEMORY_GIB or (
        host.gpu_gib or 0.0
    ) >= _XL_GPU_MEMORY_GIB


def is_auto(configured: str) -> bool:
    """Whether the config left the model choice to the host."""
    return configured.strip().lower() == AUTO_VARIANT


def _unified_memory_gib() -> float:
    from immich_memories.tracking.system_info import get_ram_gb

    return get_ram_gb()


def _gpu_memory_mb() -> int:
    from immich_memories.tracking.system_info import get_vram_mb

    return get_vram_mb()


def measure_host() -> HostMemory:
    """Read this host's unified memory (macOS) or its first NVIDIA GPU's memory."""
    if platform.system() == "Darwin":
        return HostMemory(unified_gib=_unified_memory_gib())
    vram_mb = _gpu_memory_mb()
    return HostMemory(gpu_gib=vram_mb / 1024 if vram_mb else None)


def resolve_model_variant(configured: str) -> str:
    """The configured variant, with `auto` decided by this host's memory."""
    if not is_auto(configured):
        return configured
    return choose_model_variant(configured, measure_host())
