"""The one thread the kernel library is driven from.

On CUDA the library's runtime belongs to the thread that started it: its device
context is current there only, and its compiler asserts it is on that thread. A
kernel launched, a buffer allocated or a buffer freed anywhere else fails with
CUDA_ERROR_INVALID_CONTEXT, and a free that fails aborts the process (#2785).
Metal and the CPU backends do not care, which is why a Mac never showed it.

Titles render on the render thread and stills are prepared on a pool of others,
so every call into the library goes through here instead: start, kernels,
uploads, downloads and the release of device buffers all run on this thread.
One thread also serialises them, which the runtime needs anyway.

A daemon thread rather than an executor: an executor's thread is joined before
`atexit` runs, and the runtime still has to be released on this thread then.

Nothing here imports the library: the probe still decides whether it may load.
"""

from __future__ import annotations

import contextvars
import functools
import queue
import threading
from collections.abc import Callable
from concurrent.futures import Future
from typing import ParamSpec, TypeVar

_P = ParamSpec("_P")
_T = TypeVar("_T")

_Job = Callable[[], None]

_jobs: queue.SimpleQueue[_Job] = queue.SimpleQueue()
_thread: threading.Thread | None = None
_thread_lock = threading.Lock()


def _serve() -> None:
    while True:
        job = _jobs.get()
        job()
        # Dropped here, so whatever the job held last is freed on this thread.
        del job


def _kernel_thread() -> threading.Thread:
    global _thread
    with _thread_lock:
        if _thread is None:
            _thread = threading.Thread(target=_serve, name="kernels", daemon=True)
            _thread.start()
        return _thread


def _on_kernel_thread_now() -> bool:
    return _thread is not None and threading.get_ident() == _thread.ident


def _submit(fn: Callable[[], _T]) -> Future[_T]:
    future: Future[_T] = Future()

    def job() -> None:
        if not future.set_running_or_notify_cancel():
            return
        try:
            future.set_result(fn())
        except BaseException as exc:  # noqa: BLE001 — handed to the caller, raised there
            future.set_exception(exc)

    _kernel_thread()
    _jobs.put(job)
    return future


def on_kernel_thread(fn: Callable[_P, _T], /, *args: _P.args, **kwargs: _P.kwargs) -> _T:
    """Run ``fn`` on the kernel thread and return what it returns, or raise what it raises.

    Called from the kernel thread itself it runs in place, so kernel code may call
    kernel code. The caller's context variables go with it (the run's log
    collector, its cancellation check).
    """
    if _on_kernel_thread_now():
        return fn(*args, **kwargs)
    context = contextvars.copy_context()
    return _submit(functools.partial(context.run, fn, *args, **kwargs)).result()


def runs_on_kernel_thread(fn: Callable[_P, _T]) -> Callable[_P, _T]:
    """Make every call of ``fn`` run on the kernel thread."""

    @functools.wraps(fn)
    def on_the_kernel_thread(*args: _P.args, **kwargs: _P.kwargs) -> _T:
        return on_kernel_thread(fn, *args, **kwargs)

    return on_the_kernel_thread


def release_on_kernel_thread(release: Callable[[], object]) -> None:
    """Free device buffers on the kernel thread without waiting for it.

    For finalizers: a buffer dropped on any other thread is freed there, which on
    CUDA aborts the process. ``release`` holds the last references and drops them
    where they were made.
    """
    if _on_kernel_thread_now():
        release()
        return
    _submit(release)
