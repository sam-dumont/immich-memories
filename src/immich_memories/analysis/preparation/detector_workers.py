"""The detector interpreters a preparation hands its batches to, kept between batches.

A preparation decides its pictures in batches, and each batch used to start a fresh
interpreter that imported ONNX Runtime, re-hashed the exposure model and loaded both
producers before reading a single picture. A worker here takes job after job on its
stdin (`detectors._serve`), so that start-up is paid once per idle spell, not per batch.
Parent side only: the worker itself runs `detectors.py` as a script.
"""

from __future__ import annotations

import atexit
import json
import os
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO

from immich_memories.analysis.preparation import detectors

# A worker with no job for this long exits on its own, so the detector models do not sit
# in memory beside the render once preparation is done. It covers the gap between two
# batches, which is a batch of clips being sampled. The parent stops handing it jobs
# half a minute before that, so a job never races the exit.
_IDLE_SECONDS = 120.0
_REUSE_WITHIN = _IDLE_SECONDS - 30.0
# Idle workers by (interpreter, cache dir, downloads allowed, threads): what their
# environment was started with. A worker is taken out while it runs a job, so two
# preparations at once never share one.
_IDLE: dict[tuple, _Worker] = {}
_POOL_LOCK = threading.Lock()
_EXIT_HOOK: list[bool] = []


@dataclass
class _Worker:
    """One long-lived detector interpreter that takes jobs, one line each, on its stdin."""

    process: subprocess.Popen
    interpreter: str
    directory: tempfile.TemporaryDirectory
    last_used: float = field(default_factory=time.monotonic)
    # Where this job's lines start in the log: the end of the last job that answered. A
    # worker that died at start wrote its reason before any job was sent, so the offset
    # must not be taken when the job is: that read nothing and lost the missing module.
    log_offset: int = 0

    @property
    def log_path(self) -> Path:
        return Path(self.directory.name) / "worker.log"

    def reusable(self) -> bool:
        fresh = time.monotonic() - self.last_used < _REUSE_WITHIN
        return fresh and self.process.poll() is None

    def run(
        self,
        job_path: Path,
        result_path: Path,
        poll: Callable[[], None],
        check_cancelled: Callable[[], None],
    ) -> dict[str, str]:
        stdin: IO[str] = self.process.stdin  # type: ignore[assignment]
        # A worker that died at start (a detector interpreter without numpy) has closed
        # its end; the wait below then reports what its log says, not a broken pipe.
        with suppress(OSError):
            stdin.write(json.dumps({"job": str(job_path), "result": str(result_path)}) + "\n")
            stdin.flush()
        while not result_path.is_file() and self.process.poll() is None:
            check_cancelled()
            poll()
            time.sleep(0.2)
        check_cancelled()
        if not result_path.is_file():
            raise RuntimeError(
                "detector worker failed; install required detector dependencies in "
                f"{self.interpreter}: {self._log_since(self.log_offset)[-3000:]}"
            )
        result = json.loads(result_path.read_text())
        poll()
        self.last_used = time.monotonic()
        with suppress(OSError):
            self.log_offset = self.log_path.stat().st_size
        return result

    def _log_since(self, offset: int) -> str:
        with suppress(OSError), self.log_path.open() as log:
            log.seek(offset)
            return log.read()
        return ""

    def retire(self) -> None:
        """Let the worker finish: no more jobs means it exits at the end of its input."""
        with suppress(OSError):
            self.process.stdin.close()  # type: ignore[union-attr]
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _stop_worker(self.process)
        self.directory.cleanup()

    def stop(self) -> None:
        """Stop the worker now, mid-job: a cancelled or failed run does not wait for it."""
        _stop_worker(self.process)
        self.directory.cleanup()


def _spawn(interpreter: str, cache_dir: str, allow_downloads: bool, threads: int) -> _Worker:
    directory = tempfile.TemporaryDirectory(prefix="immich-detector-worker-")
    with (Path(directory.name) / "worker.log").open("w") as log:
        process = subprocess.Popen(  # noqa: S603 — configured executable, no shell
            # Run this packaged file directly so a detector-only environment
            # does not need unrelated application/UI configuration dependencies.
            [interpreter, str(Path(detectors.__file__).resolve()), "--serve", str(_IDLE_SECONDS)],
            env=detectors.worker_env(cache_dir, allow_downloads, threads=threads),
            stdin=subprocess.PIPE,
            stdout=log,
            stderr=log,
            text=True,
            start_new_session=True,
        )
    if not _EXIT_HOOK:
        _EXIT_HOOK.append(True)
        atexit.register(retire_detector_workers)
    return _Worker(process, interpreter, directory)


def lease(key: tuple) -> _Worker:
    with _POOL_LOCK:
        worker = _IDLE.pop(key, None)
    if worker is not None and worker.reusable():
        return worker
    if worker is not None:
        worker.retire()
    return _spawn(*key)


def give_back(key: tuple, worker: _Worker) -> None:
    with _POOL_LOCK:
        if key not in _IDLE:
            _IDLE[key] = worker
            return
    worker.retire()


def retire_detector_workers() -> None:
    """Let every idle detector worker exit; the next preparation starts a fresh one."""
    with _POOL_LOCK:
        workers = list(_IDLE.values())
        _IDLE.clear()
    for worker in workers:
        worker.retire()


def _stop_worker(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait()
