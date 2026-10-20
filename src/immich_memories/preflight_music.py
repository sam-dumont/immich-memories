"""Whether the music this install is set to generate on this machine can run here.

ACE-Step in `lib` mode runs from a sibling `.venv-acestep` that `make install-acestep` creates
next to each checkout. A new clone or worktree starts without it, and a render then falls back
to a bundled track with one warning in its log. `doctor` says so before a render does.
"""

from __future__ import annotations

from immich_memories.audio.generators.ace_step_isolated import install_hint, isolated_python
from immich_memories.audio.generators.ace_step_music_path import music_path_for
from immich_memories.audio.generators.ace_step_runtime import is_ace_step_importable
from immich_memories.config.loader import Config
from immich_memories.preflight import CheckResult, CheckStatus


def check_music(config: Config) -> CheckResult:
    """Report whether ACE-Step is installed for this checkout and which source a film uses."""
    ace_step = config.ace_step
    if not ace_step.enabled:
        return CheckResult(
            "Music (ACE-Step)", CheckStatus.SKIPPED, "Not set to run on this machine"
        )
    installed = isolated_python() is not None or is_ace_step_importable()
    if ace_step.mode == "lib" and not installed:
        return CheckResult(
            "Music (ACE-Step)",
            CheckStatus.WARNING,
            "Set to run here (mode lib), but not installed",
            f"{install_hint()}, or "
            f"point advanced.ace_step at a server. Until then a render tries {ace_step.api_url} "
            "and then uses a bundled track.",
        )
    path = music_path_for(ace_step)
    if not path.generate:
        return CheckResult(
            "Music (ACE-Step)",
            CheckStatus.WARNING,
            "Films play a bundled track, not generated music",
            path.reason,
        )
    if ace_step.mode != "lib":
        return CheckResult(
            "Music (ACE-Step)", CheckStatus.OK, "The server runs XL; films generate their music"
        )
    python = isolated_python()
    return CheckResult(
        "Music (ACE-Step)",
        CheckStatus.OK,
        "Installed for this checkout" if python else "Installed in this environment",
        str(python) if python else None,
    )
