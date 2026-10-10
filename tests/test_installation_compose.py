"""Published install commands select release assets and one shared image version."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(not shutil.which("node"), reason="Node required")
@pytest.mark.parametrize("version", ["1.2.3", "v1.2.3-rc.1", "development"])
@pytest.mark.parametrize(
    ("tier", "overlays"),
    [
        ("basic", []),
        ("gpu", ["docker-compose.gpu.yml", "docker-compose.cuda.yml"]),
        (
            "full",
            ["docker-compose.gpu.yml", "docker-compose.full.yml", "docker-compose.cuda.yml"],
        ),
    ],
)
def test_installation_commands_select_assets_and_one_version(version, tier, overlays):
    module = (
        Path(__file__).resolve().parents[1]
        / "docs-site/src/components/InstallationFiles/downloads.ts"
    )
    commands = subprocess.check_output(
        [
            "node",
            "--experimental-strip-types",
            "--experimental-specifier-resolution=node",
            "--input-type=module",
            "-e",
            f"import {{installationCommands}} from {json.dumps(module.as_uri())}; console.log(installationCommands({json.dumps(version)}, {json.dumps(tier)}));",
        ],
        text=True,
    )
    assert "docker-compose.override.yml" not in commands
    assert "INFERENCE_TAG" not in commands
    if version == "development":
        assert commands.strip() == ""
    else:
        assert "IMMICH_MEMORIES_VERSION=" + version.removeprefix("v") in commands
        assert "docker build" not in commands
        downloads = re.findall(r'curl -fLO "[^"\n]+/([^/"\n]+)"', commands)
        assert downloads == ["docker-compose.yml", "example.env", *overlays]
        if tier != "basic":
            assert "TIER=" + tier in commands
            assert "COMPOSE_FILE=" + ":".join(["docker-compose.yml", *overlays]) in commands
        assert (
            "/releases/download/v1.2.3-rc.1/" if "rc" in version else "/releases/download/v1.2.3/"
        ) in commands
        assert "raw.githubusercontent.com" not in commands
