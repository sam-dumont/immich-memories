"""Evidence about this setup, keeping memory estimates distinct from execution."""

from __future__ import annotations

import asyncio
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from immich_memories.config import Config


@dataclass
class Capability:
    name: str
    status: str
    message: str


def optional_capabilities(config: Config) -> list[Capability]:
    """Expose optional readers that can otherwise quietly fall back during a film."""
    from immich_memories.analysis.editorial_laya_reader import laya_reader_for

    name = "Laya audience check"
    if not config.editorial.laya_audience:
        return [Capability(name, "skipped", "Not used by the configured selection tier")]
    try:
        reader = laya_reader_for(config.editorial)
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        return [Capability(name, "failed", f"Model could not be opened ({type(exc).__name__})")]
    if reader is None:
        return [
            Capability(
                name,
                "missing",
                "Run immich-memories models fetch; the MLX checkpoint also needs "
                "pip install laya-mlx. Until then, sharing uses heads and rules alone.",
            )
        ]
    return [Capability(name, "untested", "Model found; inference has not been tested")]


def music_capabilities(config: Config, *, test_music: bool = False) -> list[Capability]:
    """Offer smaller local profiles without calling a weight budget a successful test."""
    from immich_memories.audio.generators.ace_step_isolated import isolated_python
    from immich_memories.audio.generators.ace_step_runtime import is_ace_step_importable
    from immich_memories.audio.generators.memory_budget import (
        available_memory_bytes,
        required_memory_bytes,
    )

    installed = isolated_python() is not None or is_ace_step_importable()
    configured = config.ace_step
    profiles = dict.fromkeys(
        [
            (
                configured.model_variant.removeprefix("acestep-v15-"),
                configured.lm_model_size if configured.use_lm else None,
            ),
            ("turbo", None),
            ("turbo", "0.6B"),
        ]
    )
    rows = []
    for variant, planner in profiles:
        available = available_memory_bytes()
        name = f"ACE-Step {variant} / {planner + ' planner' if planner else 'no planner'}"
        required = required_memory_bytes(variant, planner)
        if not installed:
            rows.append(Capability(name, "missing", "Run make install-acestep in this checkout"))
        elif available is None:
            rows.append(
                Capability(name, "untested", "Cannot measure available memory; no model loaded")
            )
        elif available < required:
            rows.append(
                Capability(
                    name,
                    "blocked",
                    f"Needs {required / 2**30:.1f} GiB for weights; "
                    f"{available / 2**30:.1f} GiB available now. "
                    "An idle local model server may still hold memory; unload its model and retry.",
                )
            )
        elif test_music:
            rows.append(_test_music(name, variant, planner))
        else:
            rows.append(
                Capability(
                    name,
                    "untested",
                    f"Weight budget {required / 2**30:.1f} GiB; "
                    f"{available / 2**30:.1f} GiB available now. "
                    "Run capabilities --test-music to generate audio",
                )
            )
    return rows


def _test_music(name: str, variant: str, planner: str | None) -> Capability:
    from immich_memories.audio.generated_audio import validate_generated_audio
    from immich_memories.audio.mixer import get_audio_duration

    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix="immich-capabilities-") as directory:
            path = asyncio.run(_generate_music(variant, planner, Path(directory)))
            if abs(get_audio_duration(path) - 15) > 0.5:
                return Capability(
                    name, "failed", "Generated track does not contain 15 seconds of audio"
                )
            if reason := validate_generated_audio(path):
                return Capability(name, "failed", reason)
        return Capability(
            name,
            "verified",
            f"Generated 15 seconds of finite, audible local audio in "
            f"{time.monotonic() - started:.1f}s (including any model download/load)",
        )
    except (ImportError, OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        return Capability(
            name, "failed", f"Local generation failed ({type(exc).__name__}); see logs"
        )


async def _generate_music(variant: str, planner: str | None, directory: Path) -> Path:
    from immich_memories.audio.generators.ace_step_backend import ACEStepBackend, ACEStepConfig
    from immich_memories.audio.generators.base import GenerationRequest

    profile = ACEStepConfig(
        mode="lib",
        model_variant=variant,
        use_lm=planner is not None,
        lm_model_size=planner or "0.6B",
    )
    async with ACEStepBackend(profile) as backend:
        result = await backend.generate(
            GenerationRequest(
                prompt="instrumental acoustic guitar and piano, warm, steady rhythm",
                duration_seconds=15,
                output_dir=directory,
            )
        )
    if result.metadata.get("mode") != "lib":
        raise RuntimeError("A local capability test cannot accept an API fallback")
    return result.audio_path
