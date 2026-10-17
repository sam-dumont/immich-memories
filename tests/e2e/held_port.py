"""Web servers for the browser tests on a loopback port nobody else can take.

A port probed as free is free only until somebody binds it. Between the probe and the server
child binding it, a few seconds of imports later, a server in another xdist worker can take it:
the fake Immich binds port 0 and the kernel may hand it exactly that port. The readiness probe
then gets the other server's answer, and every test on that launch talks to the wrong server.
So the test binds the port itself and the child serves on the inherited socket.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

LISTEN_FD_ENV = "E2E_LISTEN_FD"


def serve_on_inherited_socket(app: Any) -> None:
    """Run `app` with uvicorn on the socket the test bound and handed down (child side)."""
    import uvicorn

    listening = socket.socket(fileno=int(os.environ[LISTEN_FD_ENV]))
    uvicorn.Server(uvicorn.Config(app, log_config=None)).run(sockets=[listening])


@contextmanager
def serve_on_held_port(
    argv: Sequence[str], *, env: dict[str, str], cwd: Path, log_path: Path
) -> Iterator[str]:
    """Start `argv` serving on a port bound here, yield its URL once it answers, then stop it."""
    from tests.e2e.conftest import _wait_for_server

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listening:
        listening.bind(("127.0.0.1", 0))
        url = f"http://127.0.0.1:{listening.getsockname()[1]}"
        fd = listening.fileno()
        with log_path.open("w") as log_file:
            proc = subprocess.Popen(  # noqa: S603 -- our own server bootstrap, fixed argv
                list(argv),
                stdout=log_file,
                stderr=log_file,
                cwd=cwd,
                env={**env, LISTEN_FD_ENV: str(fd)},
                pass_fds=(fd,),
            )
    # Only the child holds the port now: when it exits, nothing answers there.
    try:
        _wait_for_server(proc, base_url=url, log_path=log_path)
        yield url
    finally:
        if proc.poll() is None:
            proc.send_signal(signal.SIGINT)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
