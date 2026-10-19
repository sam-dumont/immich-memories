"""Stop a render that is already running.

A render runs in a worker thread, and a thread cannot be cancelled from outside:
`Future.cancel()` does nothing once it started. So the render watches a flag at its
seams (between clips, before each frame it writes) and registers the FFmpeg
processes it owns here, so stopping it also ends the children that would otherwise
keep going, and the single render lane of a worker frees.
"""

from __future__ import annotations

import contextlib
import subprocess
import threading
from collections.abc import Iterator
from typing import Any


class RenderStopped(BaseException):  # noqa: N818
    """The render was asked to stop, by a deadline or a cancellation.

    A BaseException, like `KeyboardInterrupt`: the render's many `except Exception`
    and `except RuntimeError` fallbacks must not turn a stop into "try the next way".
    """


def _end_children(children: list[subprocess.Popen[Any]]) -> None:
    # Imported here: the runner imports this module for its own frame writer.
    from immich_memories.processing.ffmpeg_runner import stop_owned_process

    for child in children:
        stop_owned_process(child)


class RenderControl:
    """One render's stop flag and the child processes it owns."""

    def __init__(self) -> None:
        self._stopped = threading.Event()
        self._lock = threading.Lock()
        self._children: list[subprocess.Popen[Any]] = []

    @property
    def stopped(self) -> bool:
        return self._stopped.is_set()

    def stop(self) -> None:
        """Ask the render to stop, and end its FFmpeg children without blocking the caller."""
        self._stopped.set()
        with self._lock:
            children = self._children.copy()
        if children:
            threading.Thread(
                target=_end_children, args=(children,), name="render-stop", daemon=True
            ).start()

    def __enter__(self) -> RenderControl:
        """Make this the control the render in this process answers to."""
        global _active  # noqa: PLW0603
        _active = self
        return self

    def __exit__(self, *_exc: object) -> None:
        global _active  # noqa: PLW0603
        _active = None

    def adopt(self, process: subprocess.Popen[Any]) -> None:
        with self._lock:
            self._children.append(process)
        if self.stopped:
            _end_children([process])
            raise RenderStopped("Render stopped")

    def release(self, process: subprocess.Popen[Any]) -> None:
        with self._lock, contextlib.suppress(ValueError):
            self._children.remove(process)


# One render runs per process (the pipeline holds a single-instance lock), so the
# control belongs to the process rather than to a thread: the render fans out to
# its own worker threads, and a context variable would not follow them.
_active: RenderControl | None = None


def check_render_stopped() -> None:
    """Raise `RenderStopped` at a seam of the render when it has been told to stop."""
    control = _active
    if control is not None and control.stopped:
        raise RenderStopped("Render stopped")


def adopt_child(process: subprocess.Popen[Any]) -> None:
    """Register a long-lived child (the encoder) with the active render, if any."""
    if _active is not None:
        _active.adopt(process)


def release_child(process: subprocess.Popen[Any]) -> None:
    if _active is not None:
        _active.release(process)


@contextlib.contextmanager
def owned_child(process: subprocess.Popen[Any]) -> Iterator[None]:
    """Let a stop end `process` while it runs; nothing happens without an active render."""
    control = _active
    if control is None:
        yield
        return
    control.adopt(process)
    try:
        yield
    finally:
        control.release(process)
