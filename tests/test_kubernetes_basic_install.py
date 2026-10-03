"""Rendered Kubernetes installs select Basic without requiring a GPU."""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl not installed")
def test_kubernetes_base_requests_basic_without_changing_its_cpu_contract(tmp_path, monkeypatch):
    from immich_memories.config_loader import Config

    deployment = next(
        doc
        for doc in yaml.safe_load_all(
            subprocess.check_output(
                ["kubectl", "kustomize", str(ROOT / "deploy/kubernetes/base")], text=True
            )
        )
        if doc["kind"] == "Deployment"
    )
    app = deployment["spec"]["template"]["spec"]["containers"][0]
    env = {entry["name"]: entry.get("value") for entry in app["env"]}
    assert env["IMMICH_MEMORIES_DEPLOYMENT_TIER"] == "basic"
    monkeypatch.setenv("IMMICH_MEMORIES_DEPLOYMENT_TIER", env["IMMICH_MEMORIES_DEPLOYMENT_TIER"])
    config = Config.from_yaml(tmp_path / "missing.yaml", stored={})
    assert config.tier == "basic"
    assert config.editorial.reader == "rules"
    assert config.editorial.preparation.tier == "no_captions"
    assert "nvidia.com/gpu" not in app["resources"]["limits"]
