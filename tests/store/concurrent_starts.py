"""Processes that start runs at one instant against one store, for test_concurrent_run_starts.

Each entry point runs in its own spawned process, the way it does on a real install: two web
cuts and a CLI `generate` (each one a `generate` child, so the run lifecycle is
`observe_run`), the daily timer firing (`InProcessScheduler.tick`, which also sweeps dead runs
and settles dead attempts), the HTTP trigger (`POST /api/trigger` on the real app), and a
sweeper standing for `runs list` and a web server starting up. Everything they share is real:
the store, the run leases, the automation lease, the attempt history.

Two things stand in. Immich is the picture-level fake every automation feature test uses, and
the automation's `generate` child is a stand-in that opens its run with the real tracker. A
run's work is a wait on `release`, so every run is alive while the test reads the store.

Workers report what they saw on `events` as tuples; the test reads nothing else from them.
"""

from __future__ import annotations

import os
import random
import time
import traceback
from collections.abc import Callable
from multiprocessing.synchronize import Barrier, Event
from pathlib import Path
from typing import Any

# How long a worker waits for the test before it gives up, so a broken run never hangs.
PATIENCE_SECONDS = 120.0
JITTER_SECONDS = 0.1

MANUAL_ROLES = {
    # role -> the memory type its run records, so an overwritten row shows whose it became.
    "web-cut-1": "monthly_highlights",
    "web-cut-2": "year_in_review",
    "cli-generate": "person_spotlight",
}
AUTOMATIC_ROLES = ("timer", "trigger")
SWEEPER = "sweeper"
# Patches that last as long as the short-lived worker process.
_KEEP: list[Any] = []


def run_role(role: str, config_path: Path, start: Barrier, release: Event, events: Any) -> None:
    """One process's part: set up, wait for the others, start at once, report."""
    try:
        act = _setup(role, config_path, release, events)
        start.wait(PATIENCE_SECONDS)
        if role != SWEEPER:
            # Up to a tenth of a second apart, a different order each round: the trigger's HTTP
            # path is slower than the timer's call, and without this the timer always wins.
            time.sleep(random.uniform(0, JITTER_SECONDS))  # noqa: S311 -- not a secret
        act()
    except BaseException:
        events.put(("error", role, traceback.format_exc()))
        raise


def _setup(role: str, config_path: Path, release: Event, events: Any) -> Callable[[], None]:
    from immich_memories.config.loader import load_config

    config = load_config(config_path)
    if role in MANUAL_ROLES:
        return lambda: _manual_run(role, config, release, events)
    if role == SWEEPER:
        return lambda: _sweep(config, release, events)
    _stand_in_generate_child(role, config, release, events)
    if role == "timer":
        return lambda: _timer(config, events)
    return _trigger(config, events)


def _manual_run(role: str, config: Any, release: Event, events: Any) -> None:
    """A `generate` child: the web client's cut runs one, and so does the CLI."""
    from immich_memories.db import open_store
    from immich_memories.tracking.run_observations import observe_run

    with observe_run(
        open_store(config), source="manual", memory_type=MANUAL_ROLES[role], capture_system=False
    ) as tracker:
        events.put(("run", role, tracker.run_id, os.getpid()))
        release.wait(PATIENCE_SECONDS)
    events.put(("done", role, "ended"))


def _sweep(config: Any, release: Event, events: Any) -> None:
    """What `runs list` and a starting web server do: end runs whose owner is gone."""
    from immich_memories.db import open_store
    from immich_memories.tracking.orphaned_runs import interrupt_orphaned_runs

    store = open_store(config)
    ended: list[str] = []
    sweeps = 0
    while True:
        ended.extend(interrupt_orphaned_runs(store))
        sweeps += 1
        if release.wait(0.01):
            break
    events.put(("swept", SWEEPER, ended, sweeps))


def _stand_in_generate_child(role: str, config: Any, release: Event, events: Any) -> None:
    """Every Immich read answers from one library; the `generate` child opens a real run."""
    from contextlib import ExitStack
    from unittest.mock import patch

    from immich_memories.automation.models import ProcessResult
    from immich_memories.db import open_store
    from immich_memories.tracking.run_tracker import RunTracker
    from tests.auto_library_fake import last_month
    from tests.features.automation_library import Library, immich_holding

    def child(cmd: list[str]) -> ProcessResult:
        flags = dict(arg[2:].split("=", 1) for arg in cmd if arg.startswith("--") and "=" in arg)
        tracker = RunTracker(store=open_store(config), capture_system=False)
        tracker.start_run(
            source="auto",
            memory_type=cmd[cmd.index("--memory-type") + 1],
            memory_key=flags.get("memory-key"),
            memory_category=flags.get("memory-category"),
            automation_attempt_id=flags.get("automation-attempt-id"),
        )
        events.put(("run", f"{role}-child", tracker.run_id, os.getpid()))
        release.wait(PATIENCE_SECONDS)
        film = Path(config.output.directory) / f"{tracker.run_id}.mp4"
        film.parent.mkdir(parents=True, exist_ok=True)
        film.write_bytes(b"film")
        tracker.complete_run(output_path=film)
        return ProcessResult(returncode=0, stdout="", stderr="")

    start, _ = last_month()
    library = Library().month(f"{start:%Y-%m}", 80)
    stack = ExitStack()
    stack.enter_context(immich_holding(library))
    # WHY: the `generate` child process; the stand-in opens its run with the real tracker.
    stack.enter_context(patch("immich_memories.automation.runner._execute_generate", child))
    _KEEP.append(stack)


def _timer(config: Any, events: Any) -> None:
    """The web process's daily timer, with today's slot due."""
    import asyncio

    from immich_memories.automation.in_process_scheduler import InProcessScheduler

    timer = InProcessScheduler(lambda: config)
    fired = asyncio.run(timer.tick())
    snapshot = timer.snapshot()
    events.put(("auto", "timer", fired, snapshot.last_outcome, snapshot.last_reason))


def _trigger(config: Any, events: Any) -> Callable[[], None]:
    """`POST /api/trigger` to the real app served over HTTP, then its status URL until done.

    Served by uvicorn on a loopback socket, as `immich-memories ui` serves it, with the
    lifespan off: the lifespan starts this process's own daily timer, and the timer here is
    its own process.
    """
    import socket
    import threading
    from contextlib import ExitStack
    from unittest.mock import patch

    import httpx
    import uvicorn

    from immich_memories.web import server
    from tests.web_server_fixtures import SESSION_SECRET

    os.environ["IMMICH_MEMORIES_STORAGE_SECRET"] = SESSION_SECRET
    stack = ExitStack()
    for module in ("web.server", "web.session", "web.health", "web.trigger", "web.dependencies"):
        # WHY: the config file on the host is the boundary; this process loaded its own.
        stack.enter_context(patch(f"immich_memories.{module}.get_config", lambda *_a, **_k: config))
    _KEEP.append(stack)
    listening = socket.create_server(("127.0.0.1", 0))
    port = listening.getsockname()[1]
    served = uvicorn.Server(
        uvicorn.Config(server.create_app(), lifespan="off", log_level="warning")
    )
    threading.Thread(target=served.run, kwargs={"sockets": [listening]}, daemon=True).start()
    while not served.started:
        time.sleep(0.01)
    client = httpx.Client(
        base_url=f"http://127.0.0.1:{port}",
        headers={"x-api-key": config.server.trigger_token},
        timeout=PATIENCE_SECONDS,
    )

    def post() -> None:
        answer = client.post("/api/trigger")
        if answer.status_code != 202:
            events.put(("auto", "trigger", False, answer.status_code, answer.text))
            return
        events.put(("auto", "trigger", True, 202, answer.json()["attempt_id"]))
        deadline = time.monotonic() + PATIENCE_SECONDS
        while time.monotonic() < deadline:
            state = client.get(answer.json()["status_url"]).json()
            if state["state"] != "running":
                events.put(("done", "trigger", state["state"]))
                return
            time.sleep(0.05)
        events.put(("done", "trigger", "still running"))

    return post
