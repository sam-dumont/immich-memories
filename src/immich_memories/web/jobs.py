"""Cuts and renders the web client starts: the CLI itself, as a child process, followed on disk.

Running the public command is what keeps the browser and the terminal the same product: the
argv a job runs is the command the page shows. A job's record and output live under the cache,
so a reload, a second tab or a restarted server reads the same state. One job runs at a time,
like the CLI's own lease; cancelling signals the child's whole process group.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess  # noqa: S404 - runs this package's own CLI, argv built from typed requests
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

from immich_memories.config import get_config
from immich_memories.security import (
    configured_secret_values,
    create_private_directory,
    sanitize_error_message,
    write_secret_file,
)
from immich_memories.storage_errors import storage_failure_message
from immich_memories.web.schemas import Job, JobKind, JobStatus


class JobBusy(RuntimeError):
    """Another job is running; it is carried so the page can join it instead."""

    def __init__(self, job: Job) -> None:
        super().__init__(f"A {job.kind} is already running")
        self.job = job


def _alive(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class JobRunner:
    """Start, follow and cancel the web client's jobs; records live under `root/web-jobs`."""

    def __init__(self, root: Path) -> None:
        self._dir = Path(root) / "web-jobs"
        # Old progress files have unique IDs and will never be rewritten privately.
        if self._dir.is_dir():
            self._dir.chmod(0o700)
        # Reentrant: start() holds it while active() reads records through get().
        self._lock = threading.RLock()
        self._processes: dict[str, subprocess.Popen] = {}
        self._unsaved: dict[str, Job] = {}

    def _path(self, job_id: str, suffix: str, *, progress: bool = False) -> Path:
        if re.fullmatch(r"[0-9a-f]{32}", job_id) is None:
            raise ValueError("Invalid job ID")
        root = self._dir.resolve()
        path = (root / "progress" if progress else root) / f"{job_id}.{suffix}"
        if not path.resolve().is_relative_to(root):
            raise ValueError("Invalid job ID")
        return path

    def _record(self, job_id: str) -> Path:
        return self._path(job_id, "json")

    def _log(self, job_id: str) -> Path:
        return self._path(job_id, "log")

    def progress_path(self, job_id: str) -> Path:
        """Where a job's child keeps its `--progress-file`: apart from the records, never one."""
        return self._path(job_id, "json", progress=True)

    def _save(self, job: Job) -> None:
        create_private_directory(self._dir)
        write_secret_file(self._record(job.id), job.model_dump_json(indent=2))

    def _keep(self, job: Job) -> Job:
        # A failed status write must not turn a finished child back into a running job.
        # Retry persistence on reads, so recovery does not require a server restart.
        try:
            self._save(job)
        except OSError as error:
            job = job.model_copy(
                update={
                    "error": job.error
                    or storage_failure_message(error)
                    or (
                        "Could not save job status. Check storage permissions and free space, then retry."
                    )
                }
            )
            self._unsaved[job.id] = job
        else:
            self._unsaved.pop(job.id, None)
        return job

    def get(self, job_id: str) -> Job | None:
        """The job as its record says, a vanished child reading as interrupted."""
        path = self._record(job_id)
        with self._lock:
            if job_id in self._unsaved:
                return self._keep(self._unsaved[job_id])
            if not path.is_file():
                return None
            job = Job.model_validate(json.loads(path.read_text()))
            if job.status == "running" and job_id not in self._processes and not _alive(job.pid):
                job = self._keep(
                    job.model_copy(update={"status": "interrupted", "finished_at": time.time()})
                )
            return job

    def jobs(self) -> list[Job]:
        """Every job this cache remembers, newest first."""
        if not self._dir.is_dir():
            return []
        found = [self.get(path.stem) for path in self._dir.glob("*.json")]
        return sorted((job for job in found if job), key=lambda job: job.started_at, reverse=True)

    def active(self) -> Job | None:
        """The running job, if any: the one a new page should join rather than start another."""
        if not self._dir.is_dir():
            return None
        for path in sorted(self._dir.glob("*.json"), reverse=True):
            job = self.get(path.stem)
            if job is not None and job.status == "running":
                return job
        return None

    def start(
        self,
        kind: JobKind,
        argv: list[str],
        *,
        meta: dict[str, str | int | None] | None = None,
        on_finish: Callable[[Job], Job] | None = None,
        env: dict[str, str] | None = None,
        job_id: str | None = None,
    ) -> Job:
        """Run `argv` as a child; raise JobBusy with the running job when one is already going."""
        with self._lock:
            if running := self.active():
                raise JobBusy(running)
            job_id = job_id or uuid4().hex
            create_private_directory(self._dir)
            with os.fdopen(os.open(self._log(job_id), os.O_WRONLY | os.O_CREAT, 0o600), "w") as log:
                process = subprocess.Popen(  # noqa: S603 - argv from typed requests, never a shell
                    argv,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    env=env,
                    start_new_session=True,
                )
            job = Job(
                id=job_id,
                kind=kind,
                argv=argv,
                started_at=time.time(),
                pid=process.pid,
                meta=meta or {},
            )
            self._processes[job_id] = process
            try:
                self._save(job)
            except OSError:
                # Without a durable record the page cannot follow or cancel this child.
                self._processes.pop(job_id, None)
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    with suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                raise
        threading.Thread(
            target=self._follow, args=(job_id, process, on_finish), daemon=True
        ).start()
        return job

    def _follow(
        self, job_id: str, process: subprocess.Popen, on_finish: Callable[[Job], Job] | None
    ) -> None:
        code = process.wait()
        try:
            job = self.get(job_id)
            if job is None:
                return
            status: JobStatus = (
                "cancelled" if job.cancel_requested else "succeeded" if code == 0 else "failed"
            )
            job = job.model_copy(
                update={"status": status, "exit_code": code, "finished_at": time.time()}
            )
            if on_finish is not None and status == "succeeded":
                job = self._finish(job, on_finish)
            with self._lock:
                self._keep(job)
                self._processes.pop(job_id, None)
        finally:
            # Out of the live set whatever happened above: get() then reads a record still
            # saying "running" as interrupted, instead of a page watching it forever.
            self._processes.pop(job_id, None)

    def _finish(self, job: Job, on_finish: Callable[[Job], Job]) -> Job:
        try:
            return on_finish(job)
        except Exception as error:  # noqa: BLE001 - any failure reading the result fails the job
            message = "The job finished but its result could not be read."
            reason = storage_failure_message(error)
            try:
                with self._log(job.id).open("a") as log:
                    log.write(f"\nThe job finished but its result could not be read: {error}\n")
            except OSError as log_error:
                reason = (
                    reason or storage_failure_message(log_error) or "Its log could not be saved."
                )
            return job.model_copy(
                update={"status": "failed", "error": message + (f" {reason}" if reason else "")}
            )

    def cancel(self, job_id: str) -> Job | None:
        """Stop the child: SIGTERM to its whole process group.

        The job records the cancel itself; the cut's own attempt, whose lease frees when the
        child dies, reads as interrupted, which is what happened to it.
        """
        with self._lock:
            job = self.get(job_id)
            if job is None or job.status != "running":
                return job
            job = self._keep(job.model_copy(update={"cancel_requested": True}))
            if job.pid is not None:
                with suppress(ProcessLookupError):
                    os.killpg(job.pid, signal.SIGTERM)
            return job

    def output(self, job_id: str) -> str:
        """What the child printed, with anything secret-shaped and every configured secret removed."""
        path = self._log(job_id)
        if not path.is_file():
            return ""
        text = sanitize_error_message(path.read_text(errors="replace"))
        for secret in configured_secret_values(get_config()):
            text = text.replace(secret, "***")
        return text
