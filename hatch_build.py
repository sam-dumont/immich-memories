"""A wheel ships the built web client or is not built (#1580).

The client (`make web-build`, Node 22) is not committed. The release job and the Docker image
build it before the wheel; a wheel built without it would serve only the "client not built"
page. Editable installs are source checkouts that build it with `make dev`, so they pass.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

CLIENT = Path("src/immich_memories/web/client")


def missing_client(root: str | Path, version: str) -> str | None:
    """Why this build may not go ahead, or None when it may."""
    if version == "editable" or (Path(root) / CLIENT / "index.html").is_file():
        return None
    return f"{CLIENT} is not built: run `make web-build` (needs Node 22) before building a wheel"


class CustomBuildHook(BuildHookInterface):
    """Refuse a standard wheel that would ship without the web client."""

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        del build_data
        if self.target_name == "wheel" and (problem := missing_client(self.root, version)):
            raise RuntimeError(problem)
