"""The real CLI as a child process, with the hermetic fixture editor patched in.

Every e2e path that runs `immich-memories` (the web client's jobs, the terminal comparisons,
the demo assets) starts it through this launcher: argv is config, state dir, then the CLI's own.
"""

from __future__ import annotations

CLI_BOOTSTRAP = """
import os
import sys
from pathlib import Path

import immich_memories.config_loader as config_loader

config_path = Path(sys.argv[1])
state_dir = Path(sys.argv[2])
config_loader.Config.get_default_path = classmethod(lambda cls: config_path)
config_loader.init_config_dir = lambda: state_dir

from tests.e2e.fake_editorial import install_fake_editorial_route

# A web job's child inherits the launch's host: models fetched or not, and how long a stage takes.
install_fake_editorial_route(
    stage_seconds=float(os.environ.get("E2E_STAGE_SECONDS", "0.05")),
    models_fetched=os.environ.get("E2E_MODELS", "fetched") == "fetched",
)

from immich_memories.cli import main

sys.argv = ["immich-memories", *sys.argv[3:]]
main()
"""
