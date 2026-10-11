"""Which process a pid names: its start time, so a reused pid is not mistaken for the original.

After a reboot, or once a child is gone and the pid is handed out again, a bare pid names
whatever process got it. The start time (read from /proc on Linux, from `ps` elsewhere) does
not repeat for the same pid, so a record that keeps both can tell its own process from another.
"""

from __future__ import annotations

import subprocess  # noqa: S404 - `ps` with a fixed argv, no shell
from pathlib import Path


def process_started(pid: int) -> str | None:
    """A token that changes whenever `pid` names a different process; None when it cannot be read."""
    return _from_proc(pid) or _from_ps(pid)


def _from_proc(pid: int) -> str | None:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    # The command name sits in parentheses and may contain spaces; field 22 is the start tick.
    fields = stat.rsplit(")", 1)[-1].split()
    return f"proc:{fields[19]}" if len(fields) > 19 else None


def _from_ps(pid: int) -> str | None:
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv, integer pid
            ["ps", "-o", "lstart=", "-p", str(pid)],  # noqa: S607 - ps is on every POSIX PATH
            capture_output=True,
            text=True,
            timeout=5,
            env={"LC_ALL": "C", "PATH": "/usr/bin:/bin"},
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    started = result.stdout.strip()
    return f"ps:{started}" if result.returncode == 0 and started else None
