"""The command that runs this install's CLI in a child process."""

from __future__ import annotations

import sys


def self_command() -> list[str]:
    """Argv prefix that starts this very install's CLI, never another on PATH.

    A bare `immich-memories` resolves through PATH, so with a second install (a pipx copy
    beside a venv, say) the child ran a different version than the parent that chose the
    work: an older binary could reject the config or write a store it cannot read.
    """
    return [sys.executable, "-m", "immich_memories.cli"]
