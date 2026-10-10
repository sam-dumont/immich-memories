"""Run the Basic installation's two downloads and Compose validation for a screenshot.

The commands and their output are real. The folder and Docker configuration are disposable;
this never pulls an image, starts a container or contacts an Immich server.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

_RELEASE = "https://github.com/sam-dumont/immich-memories/releases/download/v1.0.0-rc.9"


def main() -> None:
    """Capture only public release files and the local Compose parser's output."""
    plugin = shutil.which("docker-compose")
    if plugin is None:
        raise SystemExit("Install Docker Compose v2 with docker-compose on PATH first.")
    with tempfile.TemporaryDirectory(prefix="immich-compose-capture-", dir="/tmp") as scratch:
        root = Path(scratch)
        docker_config = root / "docker-config"
        docker_config.mkdir()
        # Keep plugin discovery while excluding the user's Docker config and credentials.
        (docker_config / "config.json").write_text(
            json.dumps({"cliPluginsExtraDirs": [str(Path(plugin).parent)]})
        )
        environment = {
            name: os.environ[name] for name in ("PATH", "TERM", "LANG") if name in os.environ
        }
        environment["DOCKER_CONFIG"] = str(docker_config)
        project = root / "immich-memories"
        project.mkdir()
        commands = (
            ["curl", "-fsSLO", f"{_RELEASE}/docker-compose.yml"],
            ["curl", "-fsSLO", f"{_RELEASE}/example.env"],
            ["ls", "-A"],
            ["cp", "example.env", ".env"],
            ["docker", "compose", "config", "--services"],
            ["docker", "compose", "config", "--images"],
        )
        print("\033[2J\033[3J\033[H", end="", flush=True)
        for command in commands:
            print("\n❯ " + shlex.join(command), flush=True)
            subprocess.run(command, cwd=project, env=environment, check=True)  # noqa: S603 -- fixed capture commands
        print("\n❯ ", end="", flush=True)
        # VHS hides the screen before the invoking shell's personal prompt returns.
        time.sleep(3)


if __name__ == "__main__":
    main()
