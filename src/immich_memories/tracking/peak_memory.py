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

SAMPLE_SECONDS = 0.25
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
        return int((_PROC / str(pid) / "statm").read_text().split()[1]) * _PAGE
    except (OSError, IndexError, ValueError):
        return None


def _children(pid: int) -> list[int]:
    if _LIBPROC is not None:
        pids = (ctypes.c_int * 256)()
        count = _LIBPROC.proc_listchildpids(pid, pids, ctypes.sizeof(pids))
        return [child for child in pids[: max(0, min(count, 256))] if child > 0]
    found: list[int] = []
    try:
        tasks = list((_PROC / str(pid) / "task").iterdir())
    except OSError:
        return found
    for task in tasks:
        try:
            found.extend(int(child) for child in (task / "children").read_text().split())
        except (OSError, ValueError):
            continue
    return found


def tree_rss_bytes(pid: int) -> int | None:
    """RSS of `pid` plus every live descendant, the figure an out-of-memory killer sees."""
    own = rss_bytes(pid)
    if own is None:
        return None
    total, pending, seen = own, _children(pid), {pid}
    while pending:
        child = pending.pop()
        if child in seen:
            continue
        seen.add(child)
        total += rss_bytes(child) or 0
        pending.extend(_children(child))
    return total


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
        with self._lock:
            self._open.remove(watch)
            if not self._open and self._stop is not None:
                self._stop.set()
                self._stop = None
        watch.see(rss_bytes(os.getpid()), None)
        if lifetime > watch.lifetime_at_open:
            watch.see(lifetime, None)
        # A child that ended inside the span with a new record was alive in it.
        if children > watch.children_at_open:
            watch.see(None, children)
        return watch

    def _run(self, stop: threading.Event) -> None:
        while not stop.wait(SAMPLE_SECONDS):
            pid = os.getpid()
            own = rss_bytes(pid)
            tree = tree_rss_bytes(pid)
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
