"""Whether the music this install is set to generate on this machine can run here.

ACE-Step in `lib` mode runs from a sibling `.venv-acestep` that `make install-acestep` creates
next to each checkout. A new clone or worktree starts without it, and a render then falls back
to a bundled track with one warning in its log. `doctor` says so before a render does.
"""

from __future__ import annotations

from immich_memories.audio.generators.ace_step_isolated import isolated_python
from immich_memories.audio.generators.ace_step_runtime import is_ace_step_importable
from immich_memories.config_loader import Config
from immich_memories.preflight import CheckResult, CheckStatus


def check_music(config: Config) -> CheckResult:
    """Report whether ACE-Step, set to run here, is installed for this checkout."""
    ace_step = config.ace_step
    if not ace_step.enabled or ace_step.mode != "lib":
        return CheckResult(
            "Music (ACE-Step)", CheckStatus.SKIPPED, "Not set to run on this machine"
        )
    if (python := isolated_python()) is not None:
        return CheckResult(
            "Music (ACE-Step)", CheckStatus.OK, "Installed for this checkout", str(python)
        )
    if is_ace_step_importable():
        return CheckResult("Music (ACE-Step)", CheckStatus.OK, "Installed in this environment")
    return CheckResult(
        "Music (ACE-Step)",
        CheckStatus.WARNING,
        "Set to run here (mode lib), but not installed",
        "Run `make install-acestep` in this checkout (every new clone or worktree needs it), or "
        f"point advanced.ace_step at a server. Until then a render tries {ace_step.api_url} and "
        "then uses a bundled track.",
    )
