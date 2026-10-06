"""The downloadable setup files merge through Docker Compose, not a YAML approximation."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from immich_memories.config_loader import Config

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.2.3-rc.4"


@pytest.fixture
def compose_cli():
    command = ["docker-compose"] if shutil.which("docker-compose") else ["docker", "compose"]
    if (
        not shutil.which(command[0])
        or subprocess.run([*command, "version"], capture_output=True).returncode
    ):
        pytest.skip("Docker Compose is not installed")
    return command


@pytest.mark.parametrize(
    "tier,cuda", [("basic", False), ("gpu", False), ("gpu", True), ("full", False), ("full", True)]
)
def test_tier_files_use_one_version_and_editable_service_defaults(
    compose_cli, monkeypatch, tmp_path, tier, cuda
):
    files = ["docker-compose.yml"]
    if tier != "basic":
        files.append("docker-compose.gpu.yml")
    if tier == "full":
        files.append("docker-compose.full.yml")
    if cuda:
        files.append("docker-compose.cuda.yml")
    command = [*compose_cli]
    for name in files:
        command.extend(["-f", str(ROOT / name)])
    env = {
        **os.environ,
        "IMMICH_MEMORIES_VERSION": VERSION,
        "READER_ENABLED": "true",
        "READER_URL": "http://reader.example:8000/v1",
        "READER_MODEL": "fixture-reader",
    }
    result = subprocess.run(
        [*command, "config", "--format", "json"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    services = json.loads(result.stdout)["services"]
    app = services["immich-memories"]
    assert app["image"].endswith(f":{VERSION}")
    assert app["ports"][0]["host_ip"] == "127.0.0.1"
    for key, value in app["environment"].items():
        if key.startswith("IMMICH_MEMORIES_DEPLOYMENT_"):
            monkeypatch.setenv(key, value)
    config = Config.from_yaml(tmp_path / "missing.yaml", stored={})
    assert config.tier == tier
    if tier == "basic":
        assert set(services) == {"immich-memories"}
        return
    assert int(app["deploy"]["resources"]["limits"]["memory"]) == 8 * 1024**3
    inference = services["immich-memories-inference"]
    assert inference["image"].endswith(f":{VERSION}" + ("-cuda" if cuda else ""))
    assert config.inference.facts_base_url == "http://immich-memories-inference:8092"
    assert config.inference.fallback_to_local
    assert (
        config.editorial.preparation.caption_base_url == "http://immich-memories-captioner:8092/v1"
    )
    assert "IMMICH_MEMORIES_INFERENCE__FACTS_BASE_URL" not in app["environment"]
    if cuda:
        for name in ("immich-memories-inference", "immich-memories-captioner"):
            device = services[name]["deploy"]["resources"]["reservations"]["devices"][0]
            assert device["driver"] == "nvidia" and device["capabilities"] == ["gpu"]
        assert services["immich-memories-captioner"]["image"].endswith(":server-cuda-b10920")
        assert (
            services["immich-memories-captioner"]["environment"]["LLAMA_ARG_N_GPU_LAYERS"] == "99"
        )


def test_worker_download_is_standalone_and_requires_render_auth(compose_cli, monkeypatch, tmp_path):
    shutil.copyfile(ROOT / "docker-compose.gpu-worker.yml", tmp_path / "docker-compose.yml")
    env = {
        **os.environ,
        "IMMICH_MEMORIES_VERSION": VERSION,
        "IMMICH_URL": "https://photos.example",
        "RENDER_WORKER_TOKEN": "synthetic-worker-token-for-config-only",
    }
    result = subprocess.run(
        [*compose_cli, "-f", str(tmp_path / "docker-compose.yml"), "config", "--format", "json"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    worker = json.loads(result.stdout)["services"]["gpu-worker"]
    assert worker["image"].endswith(f":{VERSION}-cuda")
    assert worker["command"] == ["python", "-m", "immich_memories_inference.gpu_worker"]
    assert worker["ports"][0]["host_ip"] == "127.0.0.1"
    assert (
        worker["environment"]["IMMICH_MEMORIES_RENDER_WORKER_TOKEN"] == env["RENDER_WORKER_TOKEN"]
    )
    # WHY: a cold writable volume must not hide the immutable CUDA model bundle.
    from immich_memories_inference.settings import InferenceSettings

    dockerfile = (ROOT / "docker/Dockerfile.inference").read_text()
    cuda_stage = dockerfile.split("AS prod-cuda", 1)[1].split("FROM prod-${DEVICE}", 1)[0]
    for line in cuda_stage.splitlines():
        if line.startswith("ENV "):
            key, value = line.removeprefix("ENV ").split("=", 1)
            monkeypatch.setenv(key, value)
    for key, value in worker["environment"].items():
        monkeypatch.setenv(key, value)
    empty_cache = tmp_path / "empty-model-cache"
    empty_cache.mkdir()
    monkeypatch.setenv("IMMICH_MEMORIES_INFERENCE_CACHE_DIR", str(empty_cache))
    settings = InferenceSettings(_env_file=None)
    assert settings.encoder_path == Path("/opt/immich-models/dinov2-small.onnx")
    assert settings.marqo_onnx_path == Path("/opt/immich-models/nsfw-marqo-384.onnx")
    assert settings.detector_cache == "/opt/immich-models/huggingface"
    assert not settings.allow_model_downloads
    assert os.environ["HF_HUB_OFFLINE"] == "1"
    caption_command = (ROOT / "docker/captioner-bundled.sh").read_text()
    assert "--model /opt/immich-models/captioner/model.gguf" in caption_command
    assert "--mmproj /opt/immich-models/captioner/mmproj.gguf" in caption_command
    assert not list(empty_cache.iterdir())
    env.pop("RENDER_WORKER_TOKEN")
    refused = subprocess.run(
        [*compose_cli, "-f", str(tmp_path / "docker-compose.yml"), "config"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert refused.returncode != 0
    assert "Set the shared render token" in refused.stderr


def test_postgres_download_and_container_harness_keep_database_readiness(compose_cli, tmp_path):
    from tests.container.deployment import Deployment

    deployment = Deployment("fixture-app:latest", "postgresql", tmp_path)
    deployment.write()
    assert (tmp_path / "docker-compose.postgres.yml").is_file()
    result = subprocess.run(
        [
            *compose_cli,
            "-f",
            str(tmp_path / "docker-compose.yml"),
            "-f",
            str(tmp_path / "docker-compose.postgres.yml"),
            "-f",
            str(tmp_path / "override.yml"),
            "config",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    services = json.loads(result.stdout)["services"]
    app = services["immich-memories"]
    assert app["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert "@postgres:5432/immich_memories" in app["environment"]["IMMICH_MEMORIES_DATABASE_URL"]
    assert services["postgres"]["image"].startswith("postgres:16@sha256:")
    assert not services["postgres"].get("ports")


@pytest.mark.parametrize("source", ["default", "example", "basic"])
def test_compose_cpu_install_uses_canonical_basic(compose_cli, tmp_path, monkeypatch, source):
    env = {key: value for key, value in os.environ.items() if key != "TIER"}
    command = [*compose_cli, "--env-file", os.devnull]
    if source == "example":
        command = [*compose_cli, "--env-file", str(ROOT / "example.env")]
    elif source == "basic":
        env["TIER"] = source
    result = subprocess.run(
        [*command, "-f", str(ROOT / "docker-compose.yml"), "config", "--format", "json"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    app = json.loads(result.stdout)["services"]["immich-memories"]
    tier = app["environment"]["IMMICH_MEMORIES_DEPLOYMENT_TIER"]
    assert tier == "basic"
    monkeypatch.setenv("IMMICH_MEMORIES_DEPLOYMENT_TIER", tier)
    config = Config.from_yaml(tmp_path / "missing.yaml", stored={})
    assert config.tier == "basic"
    assert config.editorial.reader == "rules"
    assert config.editorial.preparation.tier == "no_captions"


def test_compose_tier_env_rejects_the_legacy_nas_value(compose_cli, tmp_path, monkeypatch):
    env = {key: value for key, value in os.environ.items() if key != "TIER"}
    env["TIER"] = "nas"
    result = subprocess.run(
        [*compose_cli, "--env-file", os.devnull, "-f", str(ROOT / "docker-compose.yml"),
         "config", "--format", "json"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )  # fmt: skip
    app = json.loads(result.stdout)["services"]["immich-memories"]
    assert app["environment"]["IMMICH_MEMORIES_DEPLOYMENT_TIER"] == "nas"
    # WHY: the autouse path guard constructs Config during teardown, before monkeypatch undo.
    with monkeypatch.context() as invalid:
        invalid.setenv("IMMICH_MEMORIES_DEPLOYMENT_TIER", "nas")
        with pytest.raises(ValueError, match="tier 'nas' is now called 'basic': set tier: basic"):
            Config.from_yaml(tmp_path / "missing.yaml", stored={})
