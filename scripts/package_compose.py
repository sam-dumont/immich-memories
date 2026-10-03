"""Publish the public Compose setup files with matching release defaults."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

COMPOSE_ASSETS = (
    "docker-compose.yml",
    "example.env",
    "docker-compose.gpu.yml",
    "docker-compose.full.yml",
    "docker-compose.cuda.yml",
    "docker-compose.gpu-worker.yml",
    "docker-compose.postgres.yml",
)


def package_compose_assets(root: Path, version: str, destination: Path) -> list[Path]:
    """Render only public setup templates; local .env/config secrets never enter a release."""
    if not re.fullmatch(r"\d+\.\d+\.\d+(-(?:rc|dev)\.\d+)?", version):
        raise ValueError("Expected a release version without the v prefix")
    destination.mkdir(parents=True, exist_ok=True)
    outputs = []
    for name in COMPOSE_ASSETS:
        source = root / name
        if source.is_symlink():
            raise ValueError(f"Compose assets cannot follow symlink: {name}")
        text = source.read_text(encoding="utf-8")
        text = text.replace(
            "${IMMICH_MEMORIES_VERSION:-latest}", f"${{IMMICH_MEMORIES_VERSION:-{version}}}"
        )
        if name == "example.env":
            text, count = re.subn(
                r"(?m)^IMMICH_MEMORIES_VERSION=.*$", f"IMMICH_MEMORIES_VERSION={version}", text
            )
            if count != 1:
                raise ValueError("example.env must contain one IMMICH_MEMORIES_VERSION")
        output = destination / name
        output.write_text(text, encoding="utf-8")
        outputs.append(output)
    return outputs


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    package_compose_assets(Path(__file__).resolve().parents[1], args.version, args.destination)
