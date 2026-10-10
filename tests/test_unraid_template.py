"""Native Unraid template safety and persistence contract."""

import json
import os
import shlex
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_unraid_launch_stays_private_without_duplicate_port_mapping():
    template = ET.parse(ROOT / "deploy/unraid/immich-memories.xml").getroot()  # noqa: S314 — repository-owned template, not user input
    assert template.attrib["version"] == "2"
    assert template.findtext("Network") == "bridge"
    assert template.findtext("Privileged") == "false"
    args = shlex.split(template.findtext("ExtraParams") or "")
    assert [arg for arg in args if arg.startswith("--publish=")] == [
        "--publish=127.0.0.1:22830:8080/tcp"
    ]
    assert template.findtext("WebUI") == "http://localhost:22830"
    assert not template.findall("Config[@Type='Port']")
    assert "--security-opt=no-new-privileges:true" in args
    assert "Not yet tested on Unraid" in template.findtext("Overview")


def test_unraid_required_connection_and_writable_persistence():
    template = ET.parse(ROOT / "deploy/unraid/immich-memories.xml").getroot()  # noqa: S314 — repository-owned template, not user input
    entries = {node.attrib["Target"]: node for node in template.findall("Config")}
    for key in ("IMMICH_URL", "IMMICH_API_KEY"):
        assert entries[key].attrib["Required"] == "true"
    assert entries["IMMICH_API_KEY"].attrib["Mask"] == "true"
    for path in ("/home/immich/.immich-memories", "/app/output"):
        entry = entries[path]
        assert entry.attrib["Type"] == "Path"
        assert entry.attrib["Mode"] == "rw"
        assert (entry.text or "").startswith("/mnt/user/")
        assert "1000" in entry.attrib["Description"]
    for key in (
        "IMMICH_MEMORIES_AUTH_USERNAME",
        "IMMICH_MEMORIES_AUTH_PASSWORD",
        "IMMICH_MEMORIES_SECRET_KEY",
    ):
        assert key in (ROOT / "docker-compose.yml").read_text()
        assert not entries[key].text
    assert not any("DEPLOYMENT_" in key or "TIER" in key for key in entries)


@pytest.mark.skipif(
    not (shutil.which("docker-compose") or shutil.which("docker")),
    reason="Docker Compose unavailable",
)
def test_unraid_image_matches_resolved_compose_default():
    template = ET.parse(ROOT / "deploy/unraid/immich-memories.xml").getroot()  # noqa: S314
    executable = shutil.which("docker-compose") or shutil.which("docker")
    command = [executable] if Path(executable).name == "docker-compose" else [executable, "compose"]
    result = subprocess.run(
        [*command, "-f", str(ROOT / "docker-compose.yml"), "config", "--format=json"],
        env={**os.environ, "IMMICH_MEMORIES_VERSION": "latest"},
        capture_output=True,
        text=True,
        check=True,
    )
    assert (
        template.findtext("Repository")
        == json.loads(result.stdout)["services"]["immich-memories"]["image"]
    )
