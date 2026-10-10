"""Shipped pod policies preserve private scratch when a prepared volume is remounted."""

import stat
from pathlib import Path

import pytest
import yaml

from immich_memories.security import runtime_scratch

ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = [
    "deploy/kubernetes/base/deployment.yaml",
    "deploy/kubernetes/base/job.yaml",
    "deploy/kubernetes/overlays/inference/deployment.yaml",
    "deploy/kubernetes/overlays/captioner/deployment.yaml",
    "services/render-worker/kubernetes.yaml",
]


def _remount_prepared_volume(volume, context):
    # WHY: model kubelet's fsGroup permission pass on an already matching volume root.
    # Real scratch creation and validation run below; this does not boot a cluster.
    if context.get("fsGroupChangePolicy", "Always") == "OnRootMismatch":
        return
    for path in volume.rglob("*"):
        mode = stat.S_IMODE(path.stat().st_mode)
        path.chmod(mode | (0o2770 if path.is_dir() else 0o660))


@pytest.mark.parametrize("manifest", MANIFESTS)
def test_pod_replacement_reopens_existing_private_scratch(tmp_path, manifest):
    workload = next(
        doc
        for doc in yaml.safe_load_all((ROOT / manifest).read_text())
        if doc["kind"] in {"Deployment", "Job"}
    )
    context = workload["spec"]["template"]["spec"]["securityContext"]
    assert context["runAsUser"] == context["runAsGroup"] == context["fsGroup"] == 1000
    volume = tmp_path / "volume"
    volume.mkdir()
    volume.chmod(0o2775)
    cache = volume / "cache"
    with runtime_scratch(cache) as scratch:
        private = scratch / "retained-frame"
        private.write_bytes(b"synthetic frame")
        private.chmod(0o600)
    _remount_prepared_volume(volume, context)
    with runtime_scratch(cache) as scratch:
        assert stat.S_IMODE(scratch.stat().st_mode) & 0o777 == 0o700
        assert stat.S_IMODE(private.stat().st_mode) == 0o600
        assert private.read_bytes() == b"synthetic frame"
    assert stat.S_IMODE(volume.stat().st_mode) == 0o2775


@pytest.mark.parametrize("filename", ["main.tf", "captioner.tf"])
def test_terraform_preserves_private_directories_on_volume_remount(filename):
    import re

    source = (ROOT / "deploy/terraform" / filename).read_text()
    policies = re.findall(r'fs_group_change_policy\s*=\s*"([^"]+)"', source)
    assert policies == ["OnRootMismatch"] * len(re.findall(r"fs_group\s*=", source))
