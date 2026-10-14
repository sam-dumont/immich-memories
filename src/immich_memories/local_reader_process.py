"""Reap native reader descendants when the application's lifetime pipe closes."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading

from immich_memories.operations.bounded_process import stop_process_group


def supervise(command: list[str]) -> int:
    """Keep the native process alive only while its application still owns the pipe.

    Atexit cannot handle an application killed by the OS. The pipe reaches EOF on
    ordinary exit, crash and SIGKILL without platform-specific parent-death signals.
    """
    owner_gone = threading.Event()
    # A signal handler runs on the main thread between bytecodes, possibly while that thread
    # holds the Event's own lock inside wait(). Event.set() there deadlocks the supervisor,
    # and the application's forced stop then strands the native server in its own session
    # (#2550). The handler only appends to a list, which takes no lock.
    signalled: list[int] = []
    for kind in (signal.SIGTERM, signal.SIGINT):
        signal.signal(kind, lambda number, _frame: signalled.append(number))

    def watch_owner() -> None:
        while os.read(sys.stdin.fileno(), 1):
            pass
        owner_gone.set()

    threading.Thread(target=watch_owner, daemon=True).start()
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, start_new_session=True)
    try:
        while process.poll() is None and not signalled and not owner_gone.wait(0.05):
            pass
    finally:
        # This bound is shorter than the application's supervisor-stop deadline,
        # so its own forced cleanup cannot strand the native process group.
        stop_process_group(process, terminate_grace_seconds=3, kill_grace_seconds=3)
    return process.returncode or 0


if __name__ == "__main__":
    raise SystemExit(supervise(sys.argv[1:]))
