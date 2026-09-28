"""Cuts and renders the web client starts: the CLI itself, as a child process, followed on disk.

Running the public command is what keeps the browser and the terminal the same product: the
argv a job runs is the command the page shows. A job's record and output live under the cache,
so a reload, a second tab or a restarted server reads the same state. One job runs at a time,
like the CLI's own lease; cancelling signals the child's whole process group.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess  # noqa: S404 - runs this package's own CLI, argv built from typed requests
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

from immich_memories.security import sanitize_error_message, write_secret_file
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
        # Reentrant: start() holds it while active() reads records through get().
        self._lock = threading.RLock()
        self._processes: dict[str, subprocess.Popen] = {}

    def _record(self, job_id: str) -> Path:
        return self._dir / f"{job_id}.json"

    def _log(self, job_id: str) -> Path:
        return self._dir / f"{job_id}.log"

    def progress_path(self, job_id: str) -> Path:
        """Where a job's child keeps its `--progress-file`: apart from the records, never one."""
        return self._dir / "progress" / f"{job_id}.json"

    def _save(self, job: Job) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        write_secret_file(self._record(job.id), job.model_dump_json(indent=2))

    def get(self, job_id: str) -> Job | None:
        """The job as its record says, a vanished child reading as interrupted."""
        path = self._record(job_id)
        if not path.is_file():
            return None
        job = Job.model_validate(json.loads(path.read_text()))
        if job.status == "running" and job_id not in self._processes and not _alive(job.pid):
            with self._lock:
                # Read again under the lock: the follower may have just saved how it ended.
                job = Job.model_validate(json.loads(path.read_text()))
                if job.status == "running":
                    job = job.model_copy(
                        update={"status": "interrupted", "finished_at": time.time()}
                    )
                    self._save(job)
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
            self._dir.mkdir(parents=True, exist_ok=True)
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
            self._save(job)
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
                self._save(job)
                self._processes.pop(job_id, None)
        finally:
            # Out of the live set whatever happened above: get() then reads a record still
            # saying "running" as interrupted, instead of a page watching it forever.
            self._processes.pop(job_id, None)

    def _finish(self, job: Job, on_finish: Callable[[Job], Job]) -> Job:
        try:
            return on_finish(job)
        except Exception as error:  # noqa: BLE001 - any failure reading the result fails the job
            with self._log(job.id).open("a") as log:
                log.write(f"\nThe job finished but its result could not be read: {error}\n")
            return job.model_copy(update={"status": "failed"})

    def cancel(self, job_id: str) -> Job | None:
        """Stop the child: SIGTERM to its whole process group.

        The job records the cancel itself; the cut's own attempt, whose lease frees when the
        child dies, reads as interrupted, which is what happened to it.
        """
        job = self.get(job_id)
        if job is None or job.status != "running":
            return job
        job = job.model_copy(update={"cancel_requested": True})
        self._save(job)
        if job.pid is not None:
            with suppress(ProcessLookupError):
                os.killpg(job.pid, signal.SIGTERM)
        return job

    def output(self, job_id: str) -> str:
        """What the child printed, with anything secret-shaped removed."""
        path = self._log(job_id)
        return sanitize_error_message(path.read_text(errors="replace")) if path.is_file() else ""
