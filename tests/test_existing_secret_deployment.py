"""The public base renders without operator credentials in its working tree."""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl unavailable")
def test_base_renders_without_creating_or_loading_a_secret():
    result = subprocess.run(
        ["kubectl", "kustomize", str(ROOT / "deploy/kubernetes/base")],
        check=True,
        capture_output=True,
        text=True,
    )
    documents = list(yaml.safe_load_all(result.stdout))
    assert not any(item["kind"] == "Secret" for item in documents)
    deployment = next(item for item in documents if item["kind"] == "Deployment")
    app = deployment["spec"]["template"]["spec"]["containers"][0]
    assert {"secretRef": {"name": "immich-memories-secrets"}} in app["envFrom"]


@pytest.mark.skipif(shutil.which("terraform") is None, reason="terraform unavailable")
def test_terraform_existing_and_managed_secret_plans(tmp_path):
    module = tmp_path / "terraform"
    shutil.copytree(ROOT / "deploy/terraform", module)
    (module / "tests").mkdir(exist_ok=True)
    shutil.copyfile(
        ROOT / "tests/fixtures/terraform-existing-secret.tftest.hcl",
        module / "tests/existing-secret.tftest.hcl",
    )
    for command in (
        ["terraform", "init", "-backend=false", "-input=false"],
        ["terraform", "test", "-no-color", "-filter=tests/existing-secret.tftest.hcl"],
    ):
        result = subprocess.run(command, cwd=module, capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
