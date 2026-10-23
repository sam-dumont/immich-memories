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


def music_capabilities(config: Config, *, test_music: bool = False) -> list[Capability]:
    """Check the one ACE-Step profile films load here, without calling a weight budget a test.

    The profile is the one a local film picks: XL for ``auto`` on a host that clears the XL
    bar, the configured variant otherwise. Below the bar films play the bundled library, so
    nothing is generated and the row says so instead of passing on a model films never use.
    """
    from immich_memories.audio.generators.ace_step_isolated import install_hint, isolated_python
    from immich_memories.audio.generators.ace_step_model_choice import measure_host
    from immich_memories.audio.generators.ace_step_music_path import local_check_profile
    from immich_memories.audio.generators.ace_step_runtime import is_ace_step_importable

    settings = config.ace_step
    path, variant = local_check_profile(settings.model_variant, measure_host())
    variant = variant.removeprefix("acestep-v15-")
    planner = settings.lm_model_size if settings.use_lm else None
    name = f"ACE-Step {variant} / {planner + ' planner' if planner else 'no planner'}"
    path_row = _music_path_row(config)
    rows = [path_row] if path_row else []
    if isolated_python() is None and not is_ace_step_importable():
        rows.append(Capability(name, "missing", install_hint()))
    elif not path.generate:
        rows.append(
            Capability(
                name, "bundled", f"Not tested: films here play a bundled track; {path.reason}"
            )
        )
    else:
        rows.append(_profile_row(name, variant, planner, test_music=test_music))
    return rows


def _profile_row(name: str, variant: str, planner: str | None, *, test_music: bool) -> Capability:
    from immich_memories.audio.generators.memory_budget import (
        available_memory_bytes,
        required_memory_bytes,
    )

    available = available_memory_bytes()
    required = required_memory_bytes(variant, planner)
    if available is None:
        return Capability(name, "untested", "Cannot measure available memory; no model loaded")
    if available < required:
        return Capability(
            name,
            "blocked",
            f"Needs {required / 2**30:.1f} GiB for weights; "
            f"{available / 2**30:.1f} GiB available now. "
            "An idle local model server may still hold memory; unload its model and retry.",
        )
    if test_music:
        return _test_music(name, variant, planner)
    return Capability(
        name,
        "untested",
        f"Weight budget {required / 2**30:.1f} GiB; "
        f"{available / 2**30:.1f} GiB available now. "
        "Run capabilities --test-music to generate audio",
    )


def _music_path_row(config: Config) -> Capability | None:
    """Which source a film's music takes and why, when ACE-Step is on."""
    from immich_memories.audio.generators.ace_step_music_path import music_path_for

    if not config.ace_step.enabled:
        return None
    path = music_path_for(config.ace_step)
    if path.generate:
        return Capability("Music source", "ok", "Films generate their music with the XL model")
    return Capability("Music source", "bundled", f"Films play a bundled track: {path.reason}")


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
