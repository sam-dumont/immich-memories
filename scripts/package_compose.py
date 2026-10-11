"""Publish the public Compose setup files with matching release defaults."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

try:  # run as a script, `scripts/` is on the path; imported by tests, it is a package
    from release_pin import pin_text
except ModuleNotFoundError:
    from scripts.release_pin import pin_text

COMPOSE_ASSETS = (
    "docker-compose.yml",
    "example.env",
    "docker-compose.gpu.yml",
    "docker-compose.full.yml",
    "docker-compose.cuda.yml",
    "docker-compose.gpu-worker.yml",
    "docker-compose.postgres.yml",
    "immich-memories.xml",
)

# Assets whose source file lives outside the repository root.
ASSET_SOURCES = {"immich-memories.xml": "deploy/unraid/immich-memories.xml"}


def package_compose_assets(root: Path, version: str, destination: Path) -> list[Path]:
    """Render only public setup templates; local .env/config secrets never enter a release."""
    if not re.fullmatch(r"\d+\.\d+\.\d+(-rc\.\d+)?|nightly-\d{8}", version):
        raise ValueError("Expected a release version without the v prefix, or nightly-YYYYMMDD")
    destination.mkdir(parents=True, exist_ok=True)
    outputs = []
    for name in COMPOSE_ASSETS:
        relative = ASSET_SOURCES.get(name, name)
        source = root / relative
        if source.is_symlink():
            raise ValueError(f"Compose assets cannot follow symlink: {name}")
        text = source.read_text(encoding="utf-8")
        stamped = pin_text(relative, text, version)
        if name == "example.env" and f"IMMICH_MEMORIES_VERSION={version}" not in stamped:
            raise ValueError("example.env must contain one IMMICH_MEMORIES_VERSION")
        text = stamped
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
