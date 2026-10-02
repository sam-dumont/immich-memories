"""The published install override selects compatible images after Compose merges it."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(
    not shutil.which("node") or not (shutil.which("docker-compose") or shutil.which("docker")),
    reason="Docker Compose and Node required",
)
@pytest.mark.parametrize(
    ("released", "inference_tag"),
    [(True, None), (True, "1.0.0-rc.1-cuda"), (False, None)],
)
def test_installation_override_pins_app_and_inference(tmp_path, released, inference_tag):
    compose = ["docker-compose"] if shutil.which("docker-compose") else ["docker", "compose"]
    if subprocess.run([*compose, "version"], capture_output=True).returncode:
        pytest.skip("Docker Compose is not installed")
    if subprocess.run(
        ["node", "--experimental-strip-types", "-e", ""], capture_output=True
    ).returncode:
        pytest.skip("Node does not support TypeScript execution (requires Node 22.6+)")
    root = Path(__file__).resolve().parents[1]
    module = root / "docs-site/src/components/InstallationFiles/override.ts"
    override = subprocess.check_output(
        [
            "node",
            "--experimental-strip-types",
            "--input-type=module",
            "-e",
            f"import {{installationOverride}} from {json.dumps(module.as_uri())}; console.log(installationOverride('v1.0.0-rc.1', {str(released).lower()}));",
        ],
        text=True,
    )
    override_file = tmp_path / "override.yaml"
    override_file.write_text(override)
    env = {key: value for key, value in os.environ.items() if key != "INFERENCE_TAG"}
    if inference_tag:
        env["INFERENCE_TAG"] = inference_tag
    config = json.loads(
        subprocess.check_output(
            [
                *compose,
                "-f",
                str(root / "docker-compose.yml"),
                "-f",
                str(root / "docker-compose.gpu.yml"),
                "-f",
                str(override_file),
                "--profile",
                "inference",
                "config",
                "--format",
                "json",
            ],
            env=env,
            text=True,
        )
    )
    services = config["services"]
    repo = "ghcr.io/sam-dumont/immich-video-memory-generator"
    assert services["immich-memories"]["image"] == (
        repo + ":1.0.0-rc.1" if released else "immich-memories:development"
    )
    assert services["immich-memories-inference"]["image"] == repo + "/inference:" + (
        inference_tag or ("1.0.0-rc.1" if released else "latest")
    )
