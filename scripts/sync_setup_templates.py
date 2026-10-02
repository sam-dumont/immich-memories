"""Keep the setup builder's public templates identical to the shipped Compose files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

FILES = {
    "base": "docker-compose.yml",
    "gpu": "docker-compose.gpu.yml",
    "full": "docker-compose.full.yml",
    "cuda": "docker-compose.cuda.yml",
    "worker": "docker-compose.gpu-worker.yml",
    "postgres": "docker-compose.postgres.yml",
}


def templates(root: Path) -> str:
    return (
        json.dumps(
            {key: yaml.safe_load((root / name).read_text()) for key, name in FILES.items()},
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    output = args.output or args.source_root / "docs-site/src/components/SetupBuilder/sources.json"
    rendered = templates(args.source_root)
    if args.check:
        if not output.exists() or output.read_text() != rendered:
            raise SystemExit("Setup templates changed: run make docs-setup")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered)
