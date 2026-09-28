"""Running the product's CLI the way the gate does: its config, its store, nothing else.

The unit suite's conftest points `IMMICH_MEMORIES_DATABASE_URL` at a scratch file for the
test process, so the Makefile names the gate's store (SQLite or PostgreSQL) in
`IMMICH_GATE_DATABASE_URL` and every CLI run gets it back as the app's own variable.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from immich_memories.config_loader import Config
from immich_memories.db.bootstrap import URL_ENV, normalize_url

GATE_DATABASE_ENV = "IMMICH_GATE_DATABASE_URL"
_PROVIDER_SHORTCUTS = ("IMMICH_URL", "IMMICH_API_KEY", "OPENAI_API_KEY")


def gate_store_url() -> str:
    """The store the Makefile gave this gate run."""
    url = os.environ.get(GATE_DATABASE_ENV, "")
    if not url:
        pytest.fail(f"{GATE_DATABASE_ENV} is not set; run the gate through make test-immich-gate")
    return normalize_url(url)


def gate_env() -> dict[str, str]:
    """The environment a CLI run of the gate gets: the gate's store, no provider overrides."""
    # WHY: a developer's provider variables would override the gate's config and
    # point the run at their own library or model.
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("IMMICH_MEMORIES_", "ZAI_")) and key not in _PROVIDER_SHORTCUTS
    }
    env[URL_ENV] = gate_store_url()
    return env


def run_cli(*args: str, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    """`immich-memories --config <gate config> <args>`, output captured, never raising."""
    command = [
        str(Path(sys.executable).parent / "immich-memories"),
        "--config",
        str(Config.get_default_path()),
        *args,
    ]
    return subprocess.run(  # noqa: S603 -- our own CLI, fixed argv
        command, capture_output=True, text=True, timeout=timeout, env=gate_env(), check=False
    )
