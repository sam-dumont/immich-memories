"""Serve the real web app the way a user starts it, and talk to it over HTTP.

`immich-memories ui` runs as a child process in a sealed home (`UserHome`): its own
config at the default path, its own store, its own session key. Tests reach it over a
real socket with httpx, so what they check is what a browser or a probe gets: the
status, the headers, the body, and the address the server is listening on.
"""

from __future__ import annotations

import contextlib
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx

from tests.features.cli_harness import UserHome

_STARTUP_SECONDS = 60.0


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


# Run in a child process: the suite refuses any connection of its own past the loopback.
_LAN_PROBE = """
import socket, sys
udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    udp.connect(("192.0.2.1", 9))
except OSError:
    print("none")
    sys.exit()
address = udp.getsockname()[0]
if address.startswith("127.") or address == "0.0.0.0":
    print("none")
    sys.exit()
try:
    socket.create_connection((address, int(sys.argv[1])), timeout=2).close()
except OSError:
    print(address, "closed")
else:
    print(address, "open")
"""


def lan_answer(port: int) -> tuple[str | None, bool]:
    """This machine's own LAN address, and whether anything listens on `port` there.

    A UDP socket "connected" to a documentation address picks the interface a packet
    would leave by without sending anything; the TCP attempt never leaves the machine.
    """
    probe = subprocess.run(  # noqa: S603 -- fixed argv
        [sys.executable, "-c", _LAN_PROBE, str(port)],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    ).stdout.split()
    if probe == ["none"]:
        return None, False
    return probe[0], probe[1] == "open"


@dataclass(frozen=True, slots=True)
class ServedApp:
    """A running `immich-memories ui` and the log it is writing."""

    port: int
    log: Path

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def client(self) -> httpx.Client:
        """A cookie-keeping client that never follows a redirect on its own."""
        return httpx.Client(base_url=self.url, follow_redirects=False, timeout=30, trust_env=False)

    def output(self) -> str:
        return self.log.read_text(encoding="utf-8", errors="replace")


@contextlib.contextmanager
def served_app(
    home: UserHome, *args: str, env: dict[str, str] | None = None
) -> Iterator[ServedApp]:
    """`immich-memories ui --port <free> <args>`, up until the block ends."""
    port = free_port()
    log = home.root / f"ui-{port}.log"
    with log.open("w", encoding="utf-8") as sink:
        process = subprocess.Popen(  # noqa: S603 -- our own CLI, fixed argv
            [sys.executable, "-m", "immich_memories.cli", "ui", "--port", str(port), *args],
            stdout=sink,
            stderr=subprocess.STDOUT,
            env=home.env(env),
            cwd=home.root,
        )
    app = ServedApp(port, log)
    try:
        _wait_until_live(process, app)
        yield app
    finally:
        process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _wait_until_live(process: subprocess.Popen[bytes], app: ServedApp) -> None:
    deadline = time.monotonic() + _STARTUP_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(f"ui exited with {process.returncode}:\n{app.output()[-4000:]}")
        with contextlib.suppress(httpx.HTTPError):
            if httpx.get(f"{app.url}/health/live", timeout=2, trust_env=False).status_code == 200:
                return
        time.sleep(0.2)
    raise AssertionError(f"ui never answered /health/live:\n{app.output()[-4000:]}")
