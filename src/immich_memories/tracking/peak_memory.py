"""Peak resident memory per span, for this process and for it plus its children (ffmpeg).

A span reads its own RSS at both ends and the process-lifetime high (`ru_maxrss`) at
both ends: when the lifetime high rose inside the span, that new high is the span's
exact peak. Everything in between comes from one background thread that samples RSS
while any span is open, so a peak that is not a new lifetime high is still seen. The
thread exists only while a measured run has an open span.

No psutil: Linux reads /proc, macOS asks libproc. Anywhere else reports no peak.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import resource
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

SAMPLE_SECONDS = 1.0
# ru_maxrss is bytes on macOS and KiB on Linux.
_MAXRSS_UNIT = 1 if sys.platform == "darwin" else 1024
_PAGE = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096
_PROC = Path("/proc")
_TASKINFO = 4  # PROC_PIDTASKINFO; pti_resident_size is the second uint64 of 96 bytes
_TASKINFO_SIZE = 96


def _libproc() -> ctypes.CDLL | None:
    if sys.platform != "darwin":
        return None
    found = ctypes.util.find_library("proc")
    return ctypes.CDLL(found) if found else None


_LIBPROC = _libproc()


def rss_bytes(pid: int) -> int | None:
    """Current resident set size of one process, or None when it can't be read."""
    if _LIBPROC is not None:
        buffer = ctypes.create_string_buffer(_TASKINFO_SIZE)
        filled = _LIBPROC.proc_pidinfo(pid, _TASKINFO, ctypes.c_uint64(0), buffer, _TASKINFO_SIZE)
        return ctypes.c_uint64.from_buffer(buffer, 8).value if filled == _TASKINFO_SIZE else None
    try:
        return int(_read(_PROC / str(pid) / "statm").split()[1]) * _PAGE
    except (OSError, IndexError, ValueError):
        return None


def _read(path: Path) -> str:
    return path.read_text()


# Threads are many and almost none of them start processes, so reading every thread's
# `children` file each tick is the cost. Between full walks only the threads that had
# children at the last walk (and the main thread) are read; a process started from some
# other thread is picked up at the next full walk, and a short one that ends first is
# still covered by the lifetime children high in `Sampler.close`.
FULL_WALK_EVERY = 5


class _ThreadChildren:
    """Finds a process's direct children without reading every thread's file each tick."""

    def __init__(self) -> None:
        self._ticks = 0
        self._hot: set[str] = set()

    def children(self, pid: int) -> list[int]:
        task_dir = _PROC / str(pid) / "task"
        full = self._ticks % FULL_WALK_EVERY == 0
        self._ticks += 1
        try:
            names = [t.name for t in task_dir.iterdir()] if full else [str(pid), *self._hot]
        except OSError:
            return []
        found: list[int] = []
        hot: set[str] = set()
        for name in dict.fromkeys(names):
            try:
                kids = [int(c) for c in _read(task_dir / name / "children").split()]
            except (OSError, ValueError):
                continue
            if kids:
                hot.add(name)
                found.extend(kids)
        if full:
            self._hot = hot - {str(pid)}
        else:
            self._hot |= hot - {str(pid)}
        return found


def _libproc_children(pid: int) -> list[int]:
    pids = (ctypes.c_int * 256)()
    count = _LIBPROC.proc_listchildpids(pid, pids, ctypes.sizeof(pids))  # type: ignore[union-attr]
    return [child for child in pids[: max(0, min(count, 256))] if child > 0]


def tree_rss_bytes(pid: int, walker: _ThreadChildren | None = None) -> int | None:
    """RSS of `pid` plus every live descendant, the figure an out-of-memory killer sees.

    `walker` carries the thread cache across ticks; descendants only ever read their
    main thread's children, since the processes the app runs (ffmpeg, shells) do not
    spawn from side threads.
    """
    own = rss_bytes(pid)
    if own is None:
        return None
    roots = _libproc_children(pid) if _LIBPROC else (walker or _ThreadChildren()).children(pid)
    total, pending, seen = own, roots, {pid}
    while pending:
        child = pending.pop()
        if child in seen:
            continue
        seen.add(child)
        total += rss_bytes(child) or 0
        pending.extend(_main_thread_children(child))
    return total


def _main_thread_children(pid: int) -> list[int]:
    if _LIBPROC is not None:
        return _libproc_children(pid)
    try:
        return [int(c) for c in _read(_PROC / str(pid) / "task" / str(pid) / "children").split()]
    except (OSError, ValueError):
        return []


def _lifetime_peak(who: int) -> int:
    return resource.getrusage(who).ru_maxrss * _MAXRSS_UNIT


@dataclass(eq=False)
class Watch:
    """One open span's running peaks, in bytes."""

    own: int
    tree: int
    lifetime_at_open: int
    children_at_open: int

    def see(self, own: int | None, tree: int | None) -> None:
        self.own = max(self.own, own or 0)
        self.tree = max(self.tree, tree or 0, self.own)


class _Sampler:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._open: list[Watch] = []
        # Each sampler thread owns its stop event, so a stop never reaches its successor.
        self._stop: threading.Event | None = None

    def open(self) -> Watch:
        own = rss_bytes(os.getpid()) or 0
        watch = Watch(
            own,
            own,
            _lifetime_peak(resource.RUSAGE_SELF),
            _lifetime_peak(resource.RUSAGE_CHILDREN),
        )
        with self._lock:
            self._open.append(watch)
            if self._stop is None:
                self._stop = threading.Event()
                threading.Thread(
                    target=self._run, args=(self._stop,), name="peak-memory", daemon=True
                ).start()
        return watch

    def close(self, watch: Watch) -> Watch:
        lifetime = _lifetime_peak(resource.RUSAGE_SELF)
        children = _lifetime_peak(resource.RUSAGE_CHILDREN)
        watch.see(rss_bytes(os.getpid()), None)
        if lifetime > watch.lifetime_at_open:
            watch.see(lifetime, None)
        # A child that ended inside the span with a new record was alive in it.
        if children > watch.children_at_open:
            watch.see(None, children)
        with self._lock:
            self._open.remove(watch)
            # Every span still open was open through this one, so it saw this peak too:
            # without this a parent can report less than its child between samples.
            for enclosing in self._open:
                enclosing.see(watch.own, watch.tree)
            if not self._open and self._stop is not None:
                self._stop.set()
                self._stop = None
        return watch

    def _run(self, stop: threading.Event) -> None:
        walker = _ThreadChildren()
        while not stop.wait(SAMPLE_SECONDS):
            pid = os.getpid()
            own = rss_bytes(pid)
            tree = tree_rss_bytes(pid, walker)
            with self._lock:
                for watch in self._open:
                    watch.see(own, tree)


_sampler = _Sampler()


def watch_open() -> Watch:
    """Start following peaks for a span that is opening."""
    return _sampler.open()


def watch_close(watch: Watch) -> Watch:
    """Stop following `watch` and fold in the exact lifetime high if it rose meanwhile."""
    return _sampler.close(watch)
