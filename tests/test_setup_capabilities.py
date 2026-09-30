"""Setup advice distinguishes a memory estimate from a working music profile."""

import numpy as np
import pytest
import soundfile as sf

from immich_memories.config import Config


def test_small_music_profile_is_offered_without_claiming_generation(monkeypatch, tmp_path):
    from immich_memories.setup_capabilities import music_capabilities

    # WHY: available host memory and the separately installed audio runtime are external state.
    monkeypatch.setattr(
        "immich_memories.audio.generators.memory_budget.available_memory_bytes", lambda: 10 * 2**30
    )
    monkeypatch.setattr(
        "immich_memories.audio.generators.ace_step_isolated.isolated_python",
        lambda: tmp_path / "python",
    )
    config = Config(ace_step={"model_variant": "acestep-v15-xl-turbo", "use_lm": False})

    rows = music_capabilities(config)

    assert rows[0].status == "blocked"
    assert "21.0 GiB" in rows[0].message
    assert [(row.name, row.status) for row in rows[1:]] == [
        ("ACE-Step turbo / no planner", "untested"),
        ("ACE-Step turbo / 0.6B planner", "untested"),
    ]
    assert all("--test-music" in row.message for row in rows[1:])


@pytest.mark.parametrize("audible", [True, False])
def test_music_probe_checks_real_audio_and_keeps_the_config(monkeypatch, tmp_path, audible):
    from immich_memories.audio.generators.base import GenerationResult
    from immich_memories.setup_capabilities import music_capabilities

    used = []

    async def generate(backend, request):
        used.append((backend.config.model_variant, backend.config.use_lm))
        path = request.output_dir / "track.wav"
        wave = 0.2 * np.sin(np.arange(24000 * 15) * 2 * np.pi * 440 / 24000)
        sf.write(path, wave if audible else np.zeros_like(wave), 24000)
        return GenerationResult(path, 15, metadata={"mode": "lib"})

    # WHY: substitute host memory, installed audio Python and expensive ML generation only;
    # the CLI's audio validation reads and decodes a real WAV.
    monkeypatch.setattr(
        "immich_memories.audio.generators.memory_budget.available_memory_bytes", lambda: 8 * 2**30
    )
    monkeypatch.setattr(
        "immich_memories.audio.generators.ace_step_isolated.isolated_python",
        lambda: tmp_path / "python",
    )
    monkeypatch.setattr(
        "immich_memories.audio.generators.ace_step_backend.ACEStepBackend.generate", generate
    )
    config = Config(ace_step={"model_variant": "acestep-v15-xl-turbo", "use_lm": False})
    before = config.model_dump()

    rows = music_capabilities(config, test_music=True)

    assert used == [("turbo", False)]
    assert rows[1].status == ("verified" if audible else "failed")
    assert ("15" if audible else "silent") in rows[1].message
    assert config.model_dump() == before


def test_capabilities_command_explains_connection_evidence_and_small_profiles(
    monkeypatch, tmp_path
):
    from click.testing import CliRunner

    from immich_memories.cli import main

    # WHY: use the real CLI with this host's expensive FFmpeg/kernel probe and provider
    # connection group replaced by recorded external check results; no owner services called.
    monkeypatch.setattr("immich_memories.preflight.run_preflight_checks", lambda _config: [])
    monkeypatch.setattr(
        "immich_memories.audio.generators.memory_budget.available_memory_bytes", lambda: 4 * 2**30
    )
    monkeypatch.setattr(
        "immich_memories.audio.generators.ace_step_isolated.isolated_python",
        lambda: tmp_path / "python",
    )
    config = Config(tier="nas")

    result = CliRunner().invoke(main.commands["capabilities"], obj={"config": config})

    assert result.exit_code == 0, result.output
    assert "1080p" in result.output
    assert "no planner" in result.output
    assert "unload" in result.output
    assert "connection" in result.output.lower()
    assert "film" in result.output.lower()


@pytest.mark.parametrize("duration, mode", [(1, "lib"), (15, "api")])
def test_probe_rejects_truncated_tracks_and_api_fallback(monkeypatch, tmp_path, duration, mode):
    from immich_memories.audio.generators.base import GenerationResult
    from immich_memories.setup_capabilities import music_capabilities

    async def generate(backend, request):
        path = request.output_dir / "track.wav"
        sf.write(path, np.full(24000 * duration, 0.2), 24000)
        return GenerationResult(path, 15, metadata={"mode": mode})

    # WHY: bound the test to one memory-safe profile and replace its ML execution;
    # duration comes from the real file, not the backend's claimed duration.
    monkeypatch.setattr(
        "immich_memories.audio.generators.memory_budget.available_memory_bytes", lambda: 8 * 2**30
    )
    monkeypatch.setattr(
        "immich_memories.audio.generators.ace_step_isolated.isolated_python",
        lambda: tmp_path / "python",
    )
    monkeypatch.setattr(
        "immich_memories.audio.generators.ace_step_backend.ACEStepBackend.generate", generate
    )

    rows = music_capabilities(
        Config(ace_step={"model_variant": "turbo", "use_lm": False}), test_music=True
    )

    assert rows[0].status == "failed"


def test_unknown_memory_does_not_trigger_automatic_model_load(monkeypatch, tmp_path):
    from immich_memories.setup_capabilities import music_capabilities

    # WHY: simulate an unreadable host memory probe and an installed audio environment.
    monkeypatch.setattr(
        "immich_memories.audio.generators.memory_budget.available_memory_bytes", lambda: None
    )
    monkeypatch.setattr(
        "immich_memories.audio.generators.ace_step_isolated.isolated_python",
        lambda: tmp_path / "python",
    )

    rows = music_capabilities(Config(), test_music=True)

    assert all(row.status == "untested" for row in rows)
    assert all("Cannot measure" in row.message for row in rows)


def test_model_alias_is_tested_only_once(monkeypatch, tmp_path):
    from immich_memories.setup_capabilities import music_capabilities

    # WHY: host memory and separate environment discovery must be stable across CI hosts.
    monkeypatch.setattr(
        "immich_memories.audio.generators.memory_budget.available_memory_bytes", lambda: 10 * 2**30
    )
    monkeypatch.setattr(
        "immich_memories.audio.generators.ace_step_isolated.isolated_python",
        lambda: tmp_path / "python",
    )

    rows = music_capabilities(
        Config(ace_step={"model_variant": "acestep-v15-turbo", "use_lm": False})
    )

    assert len(rows) == 2


def test_json_report_preserves_failed_checks_and_missing_local_audio(monkeypatch):
    import json

    from click.testing import CliRunner

    from immich_memories.cli import main
    from immich_memories.preflight import CheckResult, CheckStatus

    # WHY: these are the external connection/installation checks, not capability decisions.
    monkeypatch.setattr(
        "immich_memories.preflight.run_preflight_checks",
        lambda _config: [CheckResult("Captions", CheckStatus.ERROR, "Server unavailable")],
    )
    monkeypatch.setattr(
        "immich_memories.audio.generators.ace_step_isolated.isolated_python", lambda: None
    )
    monkeypatch.setattr(
        "immich_memories.audio.generators.ace_step_runtime.is_ace_step_importable", lambda: False
    )

    result = CliRunner().invoke(
        main.commands["capabilities"], ["--json"], obj={"config": Config(tier="nas")}
    )

    assert result.exit_code == 0
    report = json.loads(result.output)
    assert report["capabilities"][1]["status"] == "check: error"
    assert all(
        row["status"] == "missing"
        for row in report["capabilities"]
        if row["name"].startswith("ACE-Step")
    )


def test_capability_report_catches_missing_laya_before_a_gpu_film(tmp_path):
    from immich_memories.setup_capabilities import optional_capabilities

    config = Config(tier="gpu", editorial={"laya_checkpoint_path": tmp_path / "missing.tar.gz"})

    rows = optional_capabilities(config)

    laya = next(row for row in rows if row.name == "Laya audience check")
    assert laya.status == "missing"
    assert "models fetch" in laya.message


def test_verify_local_flag_reports_scoped_evidence_without_changing_legacy_checks(monkeypatch):
    from click.testing import CliRunner

    from immich_memories.cli import main
    from immich_memories.setup_capabilities import Capability

    monkeypatch.setattr("immich_memories.preflight.run_preflight_checks", lambda _: [])

    async def verify(_config):
        return [
            Capability(
                "Owned reader", "verified", "Synthetic text/JSON/vision only; not a full film"
            )
        ]

    monkeypatch.setattr("immich_memories.local_capabilities.verify_local_capabilities", verify)
    result = CliRunner().invoke(
        main.commands["capabilities"], ["--verify-local", "--json"], obj={"config": Config()}
    )
    assert result.exit_code == 0, result.output
    assert '"verified"' in result.output
    assert "not a full film" in result.output
    conflict = CliRunner().invoke(
        main.commands["capabilities"], ["--verify-local", "--test-music"], obj={"config": Config()}
    )
    assert conflict.exit_code == 2


def test_verify_local_does_not_run_external_llm_preflight(monkeypatch):
    from click.testing import CliRunner

    from immich_memories.cli import main

    config = Config()
    config.llm.enabled = True
    config.llm.base_url = "https://example.invalid/v1"
    observed = []

    def checks(candidate):
        observed.append(candidate.llm.enabled)
        return []

    monkeypatch.setattr("immich_memories.preflight.run_preflight_checks", checks)
    result = CliRunner().invoke(
        main.commands["capabilities"], ["--verify-local", "--json"], obj={"config": config}
    )
    assert result.exit_code == 0, result.output
    assert observed == [False]
    assert config.llm.enabled
    assert "configured-external" in result.output
