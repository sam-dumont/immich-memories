"""Ask launchd whether a scheduled job can reach a LAN Immich (#2242).

macOS keys the Local Network permission to the resolved interpreter (the uv-managed
`python3.12`, not Terminal) and applies it when launchd starts the job. A run from Terminal
passes and the 03:00 run fails with "No route to host" (errno 65). So the only honest check is
one launchd starts itself: a temporary LaunchAgent that runs the same launcher shim with the
narrowest read-only command that exists (`config test`: authentication and the API version,
nothing searched or filmed), writes its exit status to a file, and is removed again.
"""

from __future__ import annotations

import json
import plistlib
import shlex
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from immich_memories.api.local_network import is_local_network

CHECK_LABEL = "com.immich-memories.auto-check"
WAIT_SECONDS = 20.0
_RECORD = "local-network-check.json"
_WORK_DIR = "local-network-check"

SETTINGS_PATH = "System Settings > Privacy & Security > Local Network"

Launchctl = Callable[[list[str]], "subprocess.CompletedProcess[str]"]


@dataclass(frozen=True)
class CheckOutcome:
    passed: bool
    started: bool
    interpreter: str
    timed_out: bool = False
    advice: str = ""


def resolved_interpreter() -> str:
    """The interpreter the scheduled job really runs, symlinks resolved: what macOS lists."""
    return str(Path(sys.executable).resolve())


def immich_is_on_the_local_network(url: str) -> bool:
    """Whether macOS would gate this server: a private address, not loopback or the internet."""
    host = urlsplit(url).hostname
    return host is not None and is_local_network(host)


def _launchctl(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed binary, our own arguments
        ["launchctl", *args], capture_output=True, text=True, timeout=15, check=False
    )


def _check_plist(shim: Path, config_path: Path | None, work_dir: Path) -> dict:
    out, result = work_dir / "output.log", work_dir / "exit-status"
    command = [str(shim)]
    if config_path is not None:
        command += ["--config", str(config_path)]
    command += ["config", "test"]
    # "$0" is the shim, so launchd starts exactly what the schedule starts, through the same shell.
    script = f'"$0" "$@" >{shlex.quote(str(out))} 2>&1; echo $? >{shlex.quote(str(result))}'
    return {
        "Label": CHECK_LABEL,
        "ProgramArguments": ["/bin/sh", "-c", script, *command],
        "RunAtLoad": True,
        "WorkingDirectory": str(Path.home()),
    }


def _advice(interpreter: str, *, timed_out: bool) -> str:
    waited = " It gave no answer in time." if timed_out else ""
    return (
        f"Immich is on your local network, and macOS did not let a scheduled job reach it.{waited} "
        f"Allow {interpreter} in {SETTINGS_PATH}, then run `immich-memories auto install` again. "
        "The permission belongs to that interpreter, not to Terminal."
    )


def run_check(
    *,
    shim: Path,
    config_path: Path | None,
    state_dir: Path,
    uid: int,
    interpreter: str | None = None,
    launchctl: Launchctl = _launchctl,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    wait_seconds: float = WAIT_SECONDS,
) -> CheckOutcome:
    """Run the one-shot check through launchd and remove everything it created."""
    interpreter = interpreter or resolved_interpreter()
    work_dir = state_dir / _WORK_DIR
    work_dir.mkdir(parents=True, exist_ok=True)
    plist_path = work_dir / f"{CHECK_LABEL}.plist"
    result_file = work_dir / "exit-status"
    result_file.unlink(missing_ok=True)
    plist_path.write_bytes(plistlib.dumps(_check_plist(shim, config_path, work_dir)))
    domain = f"gui/{uid}"
    try:
        started = launchctl(["bootstrap", domain, str(plist_path)])
        if started.returncode != 0:
            detail = (started.stderr or started.stdout).strip()
            return CheckOutcome(
                passed=False,
                started=False,
                interpreter=interpreter,
                advice=f"The scheduled-run check could not be started ({detail}); skipped.",
            )
        deadline = clock() + wait_seconds
        while not result_file.exists() and clock() < deadline:
            sleep(0.5)
        status = result_file.read_text().strip() if result_file.exists() else None
        if status == "0":
            return CheckOutcome(passed=True, started=True, interpreter=interpreter)
        return CheckOutcome(
            passed=False,
            started=True,
            interpreter=interpreter,
            timed_out=status is None,
            advice=_advice(interpreter, timed_out=status is None),
        )
    finally:
        launchctl(["bootout", f"{domain}/{CHECK_LABEL}"])
        plist_path.unlink(missing_ok=True)
        result_file.unlink(missing_ok=True)
        (work_dir / "output.log").unlink(missing_ok=True)


def record_check(state_dir: Path, outcome: CheckOutcome) -> None:
    """Remember which interpreter was checked: the grant is lost when that path changes."""
    if not outcome.started:
        return
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / _RECORD).write_text(
        json.dumps({"interpreter": outcome.interpreter, "passed": outcome.passed})
    )


def interpreter_note(state_dir: Path, *, current: str | None = None) -> str | None:
    """Say so when the scheduled interpreter is not the one that was checked, else None."""
    try:
        recorded = json.loads((state_dir / _RECORD).read_text())["interpreter"]
    except (OSError, ValueError, KeyError):
        return None
    current = current or resolved_interpreter()
    if recorded == current:
        return None
    return (
        f"Scheduled runs now use {current}; the Local Network check was made for {recorded}. "
        "A uv Python upgrade moves it and macOS asks again. "
        "Run `immich-memories auto install` to check again."
    )
