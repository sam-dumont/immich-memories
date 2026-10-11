"""`immich-memories ui` started the way a user starts it, for feature tests that ask it over HTTP."""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx

from tests.features.cli_harness import UserHome


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@contextmanager
def serve_ui(home: UserHome, *args: str, port: int, host: str = "127.0.0.1") -> Iterator[Path]:
    """`immich-memories <args>` serving the UI until the block ends; yields its log file."""
    log = home.root / f"ui-{port}.log"
    with log.open("w") as sink:
        server = subprocess.Popen(  # noqa: S603 -- our own CLI, fixed argv
            [sys.executable, "-m", "immich_memories.cli", *args],
            stdout=sink,
            stderr=subprocess.STDOUT,
            env=home.env(),
            cwd=home.root,
        )
        try:
            _wait_until_live(f"http://{host}:{port}", server, log)
            yield log
        finally:
            server.terminate()
            try:
                server.wait(timeout=15)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)


def _wait_until_live(url: str, server: subprocess.Popen, log: Path) -> None:
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if server.poll() is not None:
            raise AssertionError(f"ui exited {server.returncode}:\n{log.read_text()[-3000:]}")
        try:
            if httpx.get(f"{url}/health/live", timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise AssertionError(f"ui never answered on {url}:\n{log.read_text()[-3000:]}")
