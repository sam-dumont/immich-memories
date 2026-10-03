"""Refuse versioned setup docs until the matching public deployment assets exist."""

from __future__ import annotations

import json
import re
import sys

from package_compose import COMPOSE_ASSETS


def check_release_assets(version: str, release: dict) -> list[str]:
    """Return absent artifact names, deriving Compose names from its publisher."""
    clean = version.removeprefix("v")
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-(?:rc|dev)\.\d+)?", clean):
        raise ValueError("Expected a stable or candidate release version")
    if release.get("tagName") != f"v{clean}":
        raise ValueError("Release tag does not match the docs version")
    names = {
        asset["name"]
        for asset in release["assets"]
        if asset.get("state") == "uploaded" and asset.get("size", 0) > 0
    }
    expected = (
        *COMPOSE_ASSETS,
        f"immich-memories-deploy-{clean}.tar.gz",
        "SHA256SUMS",
        "installation.json",
    )
    if "-dev." in clean:
        python_version = clean.replace("-dev.", ".dev")
        expected += (f"immich_memories-{python_version}-py3-none-any.whl",)
    return [name for name in expected if name not in names]


if __name__ == "__main__":
    missing = check_release_assets(sys.argv[1], json.load(sys.stdin))
    if missing:
        print(
            "Cannot publish versioned setup docs: missing or unfinished release assets: "
            + ", ".join(missing),
            file=sys.stderr,
        )
        raise SystemExit(1)
