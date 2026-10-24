#!/usr/bin/env python3
"""Validate the all-local music pipeline with the model films use.

Runs ACE-Step (lib mode) + Demucs (local) end-to-end with no API servers. ACE-Step runs
with `model_variant: auto`, the films' default, so it loads the 4B XL model on a host that
clears the XL bar. On a smaller host films play the bundled library and generate nothing;
the check says so and fails instead of passing on the 2B model.

Usage:
    .venv/bin/python scripts/validate_local_audio.py                 # XL, no planner
    .venv/bin/python scripts/validate_local_audio.py --quality high  # XL + 4B planner

Requirements:
    make install-acestep
    make check-local-audio

Model cache locations:
    ACE-Step: ~/.cache/ace-step/checkpoints/  (~20GB for XL-turbo + shared assets, ~28GB with 4B LM)
    Demucs:   ~/.cache/torch/hub/        (~80MB for htdemucs)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import resource
import sys
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from immich_memories.audio.generators.ace_step_backend import ACEStepConfig
    from immich_memories.audio.generators.ace_step_model_choice import HostMemory

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("validate_local_audio")


def build_acestep_config(quality: str) -> ACEStepConfig:
    """The films' own model choice (`auto`), without a planner or with the 4B one."""
    from immich_memories.audio.generators.ace_step_backend import ACEStepConfig

    return ACEStepConfig(
        mode="lib",
        model_variant="auto",
        lm_model_size="4B",
        use_lm=quality == "high",
    )


def bundled_reason(host: HostMemory) -> str | None:
    """Why films on this host play the bundled library; None when they generate with XL."""
    from immich_memories.audio.generators.ace_step_music_path import local_check_profile

    path, _variant = local_check_profile("auto", host)
    return None if path.generate else path.reason


def check_dependencies() -> dict[str, bool]:
    """Check which audio ML packages are installed."""
    import importlib.util

    deps = {}
    for pkg in ("acestep", "demucs", "torch", "torchaudio"):
        deps[pkg] = importlib.util.find_spec(pkg) is not None
    from immich_memories.audio.generators.ace_step_isolated import isolated_python

    deps["acestep"] = deps["acestep"] or isolated_python() is not None
    return deps


def get_peak_memory_mb() -> float:
    """Get peak RSS in MB (macOS/Linux)."""
    peak = max(
        resource.getrusage(kind).ru_maxrss
        for kind in (resource.RUSAGE_SELF, resource.RUSAGE_CHILDREN)
    )
    # macOS reports in bytes, Linux in KB
    if sys.platform == "darwin":
        return peak / (1024 * 1024)
    return peak / 1024


async def run_acestep(output_dir: Path, quality: str) -> Path | None:
    """Generate music with ACE-Step lib mode."""
    try:
        from immich_memories.audio.generators.ace_step_backend import ACEStepBackend
        from immich_memories.audio.generators.base import GenerationRequest
    except ImportError:
        logger.error("immich-memories not installed")
        return None

    config = build_acestep_config(quality)

    logger.info(f"ACE-Step config: variant={config.model_variant}, lm={config.lm_model_size}")

    from immich_memories.audio.generators.ace_step_isolated import isolated_python
    from immich_memories.audio.generators.ace_step_runtime import is_ace_step_importable

    if not isolated_python() and not is_ace_step_importable():
        raise RuntimeError("Local ACE-Step is missing. Run make install-acestep first.")
    backend = ACEStepBackend(config)
    if not await backend.is_available():
        logger.error("ACE-Step not available (acestep package missing)")
        return None

    request = GenerationRequest(
        prompt="upbeat happy nostalgic",
        duration_seconds=15,
        output_dir=output_dir,
    )

    start = time.monotonic()
    result = await backend.generate(request)
    if result.metadata.get("mode") != "lib":
        raise RuntimeError("The local check cannot use an API server.")
    validate_audio(result.audio_path, require_sound=True)
    elapsed = time.monotonic() - start

    logger.info(f"ACE-Step generated: {result.audio_path} ({elapsed:.1f}s)")
    logger.info(f"  Peak memory: {get_peak_memory_mb():.0f} MB")

    # Release model memory
    await backend.__aexit__()
    return result.audio_path


async def run_demucs(audio_path: Path, output_dir: Path) -> bool:
    """Separate stems with local Demucs."""
    try:
        from immich_memories.audio.generators.demucs_local import DemucsLocalBackend
    except ImportError:
        logger.error("immich-memories not installed")
        return False

    backend = DemucsLocalBackend(model_name="htdemucs")
    if not await backend.is_available():
        logger.error("Demucs not available (demucs package missing)")
        return False

    start = time.monotonic()
    stems = await backend.separate_stems(audio_path, output_dir)
    for path in (stems.vocals, stems.drums, stems.bass, stems.other):
        if path is None:
            raise RuntimeError("Demucs did not produce all four stems")
        validate_audio(path)
    elapsed = time.monotonic() - start

    logger.info(f"Demucs separated {4 if stems.has_full_stems else 2} stems ({elapsed:.1f}s)")
    logger.info(f"  vocals: {stems.vocals} ({stems.vocals.stat().st_size // 1024}KB)")
    if stems.drums:
        logger.info(f"  drums:  {stems.drums} ({stems.drums.stat().st_size // 1024}KB)")
    if stems.bass:
        logger.info(f"  bass:   {stems.bass} ({stems.bass.stat().st_size // 1024}KB)")
    if stems.other:
        logger.info(f"  other:  {stems.other} ({stems.other.stat().st_size // 1024}KB)")
    logger.info(f"  Peak memory: {get_peak_memory_mb():.0f} MB")

    backend.release()
    return True


def validate_audio(path: Path, *, require_sound: bool = False) -> None:
    """Check real samples and duration, allowing silent instrumental vocal stems."""
    import numpy as np
    import soundfile as sf

    samples, rate = sf.read(path, dtype="float32", always_2d=True)
    duration = len(samples) / rate
    if abs(duration - 15) > 0.5 or not np.isfinite(samples).all():
        raise RuntimeError(f"Invalid audio duration or samples: {path.name}")
    if require_sound and np.max(np.abs(samples)) < 0.001:
        raise RuntimeError("ACE-Step produced silent audio")
    logger.info("Verified %s: %.2fs, %d Hz", path.name, duration, rate)


async def main():
    parser = argparse.ArgumentParser(description="Validate all-local music pipeline")
    parser.add_argument(
        "--quality",
        choices=["low", "high"],
        default="low",
        help="low=XL without a planner (the films' default), high=XL with the 4B planner",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(tempfile.gettempdir()) / "immich-local-audio-test",
        help="Output directory for generated files",
    )
    args = parser.parse_args()

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 60)
    logger.info("  LOCAL AUDIO PIPELINE VALIDATION")
    logger.info("=" * 60)

    # 1. Check dependencies
    deps = check_dependencies()
    logger.info(f"Dependencies: {deps}")
    missing = [k for k, v in deps.items() if not v]
    if missing:
        logger.warning(f"Missing packages: {missing}")
        logger.info("Install with: make install-acestep (ACE-Step runs in its own environment)")

    # 2. Films on a host below the XL bar never generate: nothing here would prove anything.
    from immich_memories.audio.generators.ace_step_model_choice import measure_host

    if reason := bundled_reason(measure_host()):
        logger.info("")
        logger.info("  NOT TESTED: films here play the bundled library, not generated music.")
        logger.info(f"  {reason[0].upper()}{reason[1:]}.")
        sys.exit(1)

    # 3. ACE-Step generation
    logger.info("")
    logger.info("--- ACE-Step (lib mode) ---")
    audio_path = await run_acestep(output_dir, args.quality)

    # 4. Demucs stem separation
    if audio_path:
        logger.info("")
        logger.info("--- Demucs (local) ---")
        stems_dir = output_dir / "stems"
        success = await run_demucs(audio_path, stems_dir)
    else:
        success = False

    # 5. Summary
    logger.info("")
    logger.info("=" * 60)
    if audio_path and success:
        logger.info("  PASS: Full local pipeline works!")
        logger.info(f"  Peak memory: {get_peak_memory_mb():.0f} MB")
        logger.info(f"  Output: {output_dir}")
    else:
        logger.info("  FAIL: See errors above")
        sys.exit(1)
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
