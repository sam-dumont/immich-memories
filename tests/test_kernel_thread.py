"""Every call into the kernel library runs on one thread, whoever makes it (#2785).

On CUDA the library's runtime belongs to the thread that started it; stills are
prepared on a pool of threads and titles on the render thread.
"""

from __future__ import annotations

import contextvars
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from immich_memories.titles.kernel_thread import (
    on_kernel_thread,
    release_on_kernel_thread,
    runs_on_kernel_thread,
)


def test_calls_from_different_threads_all_run_on_one_thread():
    with ThreadPoolExecutor(4, thread_name_prefix="prepare") as pool:
        callers = list(pool.map(lambda _: threading.get_ident(), range(4)))
        ran_on = list(pool.map(lambda _: on_kernel_thread(threading.get_ident), range(16)))

    assert len(set(ran_on)) == 1
    assert ran_on[0] not in callers
    assert on_kernel_thread(threading.get_ident) == ran_on[0]


def test_kernel_code_calling_kernel_code_runs_in_place():
    @runs_on_kernel_thread
    def inner() -> int:
        return threading.get_ident()

    @runs_on_kernel_thread
    def outer() -> tuple[int, int]:
        return threading.get_ident(), inner()

    outer_thread, inner_thread = outer()

    assert outer_thread == inner_thread


def test_the_callers_error_and_context_cross_over():
    run = contextvars.ContextVar("run", default="none")
    run.set("this run")

    def failing():
        raise ValueError(run.get())

    with pytest.raises(ValueError, match="this run"):
        on_kernel_thread(failing)


def test_a_release_runs_on_the_kernel_thread():
    kernel_thread = on_kernel_thread(threading.get_ident)
    released = threading.Event()
    released_on: list[int] = []

    def release():
        released_on.append(threading.get_ident())
        released.set()

    threading.Thread(target=release_on_kernel_thread, args=(release,)).start()

    assert released.wait(5)
    assert released_on == [kernel_thread]
