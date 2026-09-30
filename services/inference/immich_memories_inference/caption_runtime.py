"""Lazy, bounded lifecycle of the caption runtime already bundled in the CUDA image."""

import os
import subprocess
import threading
from time import monotonic, sleep

import httpx


class CaptionUnavailable(RuntimeError):
    """A payload-free failure from the owned caption process."""


class CaptionRuntime:
    def __init__(
        self,
        *,
        port: int = 8094,
        command: list[str] | None = None,
        startup_timeout: float = 120,
        stop_timeout: float = 10,
    ):
        self.base_url = f"http://127.0.0.1:{port}"
        self._port = port
        self._command = command or ["/usr/local/bin/immich-memories-captioner"]
        self._startup_timeout = startup_timeout
        self._stop_timeout = stop_timeout
        self._lock = threading.Lock()
        self._process: subprocess.Popen | None = None

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self) -> None:
        with self._lock:
            if self.running:
                return
            try:
                self._process = subprocess.Popen(
                    self._command,
                    env=os.environ | {"CAPTION_HOST": "127.0.0.1", "CAPTION_PORT": str(self._port)},
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self._wait_ready()
            except (OSError, CaptionUnavailable):
                self._stop()
                raise CaptionUnavailable("Bundled caption runtime is unavailable") from None

    def _wait_ready(self) -> None:
        deadline = monotonic() + self._startup_timeout
        with httpx.Client(timeout=1, trust_env=False, follow_redirects=False) as client:
            while monotonic() < deadline and self.running:
                try:
                    if client.get(f"{self.base_url}/health").status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                sleep(0.05)
        raise CaptionUnavailable("Bundled caption runtime did not become ready")

    def stop(self) -> None:
        with self._lock:
            self._stop()

    def _stop(self) -> None:
        process = self._process
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=self._stop_timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=self._stop_timeout)
        self._process = None
