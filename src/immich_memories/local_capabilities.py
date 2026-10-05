"""Read-only owned-runtime evidence, distinct from explicit synthetic verification."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import httpx

from immich_memories.config import Config
from immich_memories.conformance.local_reader_smoke import verify_reader as _verify_reader
from immich_memories.setup_capabilities import Capability


def local_capabilities(config: Config) -> list[Capability]:
    """Describe local configuration without contacting any model provider."""
    if not config.llm.enabled:
        reader = Capability("Owned reader", "disabled", "LLM requests are disabled")
    elif config.llm.base_url.strip():
        reader = Capability(
            "Owned reader",
            "configured-external",
            "External provider configured; not certified by local verification",
        )
    else:
        from immich_memories.local_inference import local_reader_files

        try:
            local_reader_files(config.llm)
        except (FileNotFoundError, ValueError, RuntimeError) as error:
            reader = Capability("Owned reader", "missing", str(error))
        else:
            reader = Capability(
                "Owned reader",
                "unverified",
                "Runtime and model files installed; inference has not been tested",
            )
    rows = [reader, _music_capability(config)]
    installed = importlib.util.find_spec("demucs") is not None
    rows.append(
        Capability(
            "Local stems",
            "unverified" if installed else "missing",
            "Demucs installed; separation not tested" if installed else "Install the demucs extra",
        )
    )
    return rows


def _music_capability(config: Config) -> Capability:
    from immich_memories.audio.generators.ace_step_isolated import install_hint, isolated_python
    from immich_memories.audio.generators.ace_step_runtime import is_ace_step_importable
    from immich_memories.audio.generators.memory_budget import memory_shortfall

    if not config.ace_step.enabled:
        return Capability("Local music", "disabled", "ACE-Step generation is disabled")
    if config.ace_step.mode != "lib":
        return Capability(
            "Local music", "configured-external", "API music configured; not contacted or certified"
        )
    if isolated_python() is None and not is_ace_step_importable():
        return Capability("Local music", "missing", install_hint())
    planner = config.ace_step.lm_model_size if config.ace_step.use_lm else None
    if shortfall := memory_shortfall(config.ace_step.model_variant, planner):
        return Capability("Local music", "blocked", str(shortfall))
    return Capability(
        "Local music",
        "unverified",
        "Installed and configured locally; weights and generation have not been tested",
    )


async def verify_local_capabilities(config: Config, *, verifier=None) -> list[Capability]:
    """Verify only configured owned components; never certify an external provider."""
    rows = local_capabilities(config)
    if not any(
        row.status in {"unverified", "blocked"} and row.name in {"Owned reader", "Local music"}
        for row in rows
    ):
        return rows
    if verifier is None:
        verifier = _verify_owned
    tested = await verifier(config)
    replacements = {row.name: row for row in tested}
    return [
        replacements.get(row.name, row)
        if row.status == "unverified" or (row.name == "Local music" and row.status == "blocked")
        else row
        for row in rows
    ]


async def _verify_owned(config: Config) -> list[Capability]:
    """Run the owned APIs; every positive result describes only this synthetic smoke."""
    import tempfile

    from immich_memories.local_inference import local_models

    results = []
    try:
        reader = next(row for row in local_capabilities(config) if row.name == "Owned reader")
        if reader.status == "unverified":
            try:
                await _verify_reader(config)
            except (OSError, RuntimeError, ValueError, httpx.HTTPError) as error:
                results.append(Capability("Owned reader", "blocked", str(error)))
            else:
                results.append(
                    Capability(
                        "Owned reader",
                        "verified",
                        "Synthetic text, JSON enum and vision passed; not a full-film certificate",
                    )
                )
        await local_models.release()
        music = next(row for row in local_capabilities(config) if row.name == "Local music")
        if music.status == "unverified":
            with tempfile.TemporaryDirectory(prefix="immich-local-capabilities-") as temporary:
                results.extend(await _verify_audio(config, Path(temporary)))
        else:
            results.append(music)
        return results
    finally:
        await local_models.release()


async def _verify_stems(config: Config, audio_path: Path, directory: Path) -> Capability:
    from unittest.mock import patch

    from immich_memories.audio.generators.demucs_local import DemucsLocalBackend

    stems = DemucsLocalBackend()
    try:
        # Demucs uses Torch Hub rather than Hugging Face. Refuse its download
        # boundary so a missing cached checkpoint fails before network access.
        with patch(
            "torch.hub.download_url_to_file",
            side_effect=RuntimeError(
                "Demucs weights missing; install separately before --verify-local"
            ),
        ):
            result_stems = await stems.separate_stems(audio_path, directory / "stems")
        for name in ("vocals", "drums", "bass", "other"):
            _check_audio(getattr(result_stems, name), audible=False)
        if config.llm.enabled and not config.llm.base_url.strip():
            await _verify_reader(config)
        return Capability(
            "Local stems", "verified", "Four finite 15-second local Demucs stems passed"
        )
    finally:
        stems.release()


def _check_audio_assets(config: Config) -> None:
    """Refuse before loading anything when the pinned snapshot a render reads is incomplete.

    Renders load the pinned snapshot under the checkpoint root, never the root itself, so
    this asks the render's own completeness rule about that same directory.
    """
    import os

    from immich_memories.audio.generators.ace_step_checkpoints import missing_pinned_components
    from immich_memories.audio.generators.ace_step_runtime import _dit_model_name, _lm_model_name

    root = Path(
        os.environ.get("ACESTEP_CHECKPOINTS_DIR", str(Path.home() / ".cache/ace-step/checkpoints"))
    ).expanduser()
    planner = _lm_model_name(config.ace_step.lm_model_size) if config.ace_step.use_lm else None
    missing = missing_pinned_components(
        root, _dit_model_name(config.ace_step.model_variant), planner
    )
    if missing:
        raise RuntimeError(
            f"Local ACE weights missing ({', '.join(missing)}); generate one film with music "
            "or run `immich-memories capabilities --test-music` to fetch them, then "
            "--verify-local again"
        )


async def _verify_audio(config: Config, directory: Path) -> list[Capability]:
    import os
    from unittest.mock import patch

    from immich_memories.audio.generated_audio import validate_generated_audio
    from immich_memories.audio.generators.ace_step_backend import ACEStepBackend
    from immich_memories.audio.generators.base import GenerationRequest
    from immich_memories.audio.generators.factory import _app_config_to_ace_step
    from immich_memories.local_inference import local_models

    rows = []
    try:
        _check_audio_assets(config)
        await local_models.release()
        settings = config.ace_step
        profile = _app_config_to_ace_step(settings)
        profile.mode = "lib"
        profile.timeout_seconds = min(settings.timeout_seconds, 1800)
        profile.num_versions = 1
        # Local verification never forwards API credentials. Keep the app's
        # actual configured runtime/offload settings rather than a smaller profile.
        profile.extra_args.pop("api_key", None)
        # The installed local API and configured profile are required; no API fallback allowed.
        backend = ACEStepBackend(profile)
        if backend._get_effective_mode() != "lib":
            raise RuntimeError("Local ACE runtime unavailable; external fallback is forbidden")
        with patch.dict(
            os.environ,
            {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "MODELSCOPE_OFFLINE": "1"},
        ):
            async with backend:
                result = await backend.generate(
                    GenerationRequest(
                        prompt="instrumental acoustic guitar and piano, warm steady rhythm",
                        duration_seconds=15,
                        output_dir=directory / "music",
                    )
                )
        if result.metadata.get("mode") != "lib":
            raise RuntimeError("Local audio test cannot certify an API fallback")
        _check_audio(result.audio_path, audible=True)
        if reason := validate_generated_audio(result.audio_path):
            raise RuntimeError(reason)
        rows.append(
            Capability(
                "Local music",
                "verified",
                f"Configured local ACE {profile.model_variant}, planner={profile.use_lm}, "
                f"cpu_offload={bool(profile.extra_args.get('cpu_offload', False))} generated "
                "15 seconds of finite audible audio; not a full-film certificate",
            )
        )
        if config.llm.enabled and not config.llm.base_url.strip():
            await _verify_reader(config)
        rows.append(await _verify_stems(config, result.audio_path, directory))
    except (
        ImportError,
        OSError,
        RuntimeError,
        ValueError,
        httpx.HTTPError,
        subprocess.SubprocessError,
    ) as error:
        name = "Local stems" if rows else "Local music"
        rows.append(Capability(name, "blocked", str(error)))
    return rows


def _check_audio(path: Path, *, audible: bool) -> None:
    import numpy as np
    import soundfile as sf

    samples, rate = sf.read(path, dtype="float32", always_2d=True)
    if not len(samples) or not np.isfinite(samples).all() or abs(len(samples) / rate - 15) > 0.5:
        raise RuntimeError("Expected 15 seconds of finite audio")
    if audible and float(np.max(np.abs(samples))) < 1e-5:
        raise RuntimeError("Generated audio is silent")
