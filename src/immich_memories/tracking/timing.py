"""Task-local spans, buffered until a run is saved. Worker pools copy this context."""

from __future__ import annotations

import logging
import time
import traceback
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from itertools import count
from typing import Any

from immich_memories.logging_config import SecretRedactionFilter, redact_secrets
from immich_memories.process_start import Startup
from immich_memories.tracking import peak_memory

# The lines a run keeps for its report; the report shows the tail, the counts cover all.
LOG_LINES = 5000

_active: ContextVar[Collector | None] = ContextVar("run_timing", default=None)
_parent: ContextVar[Span | None] = ContextVar("timing_parent", default=None)


@dataclass
class Span:
    span_id: int
    name: str
    parent_id: int | None
    start: float
    duration: float = 0.0
    items: int | None = None
    attributes: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: dict[str, Any] | None = None
    # Resident bytes at the span's highest point: this process, and it plus its children.
    peak_rss: int | None = None
    peak_tree_rss: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Portable representation shared by the store, reports and matrix exports."""
        return asdict(self)


@dataclass
class Collector:
    run_id: str | None = None
    now: Callable[[], float] = time.perf_counter
    spans: list[Span] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    private_terms: set[str] = field(default_factory=set)
    private_ids: set[str] = field(default_factory=set)
    _ids: Any = field(default_factory=lambda: count(1), repr=False)

    def interval(self, name: str, start: float, duration: float, items: int | None) -> None:
        """Fold an existing progress clock into the same span buffer."""
        parent = _parent.get()
        self.spans.append(
            Span(
                next(self._ids),
                name,
                parent.span_id if parent else None,
                start,
                duration,
                items=items,
            )
        )


class _RunLogHandler(logging.Handler):
    def __init__(self, collector: Collector) -> None:
        super().__init__()
        self.collector = collector
        self.addFilter(SecretRedactionFilter())

    def emit(self, record: logging.LogRecord) -> None:
        if active() is not self.collector:
            return
        message = self.format(record)
        counts = self.collector.diagnostics.setdefault("log_counts", {})
        counts[record.levelname] = counts.get(record.levelname, 0) + 1
        logs = self.collector.logs
        logs.append(message)
        if len(logs) > LOG_LINES:
            del logs[: len(logs) - LOG_LINES]
        current = _parent.get()
        if record.levelno >= logging.WARNING and current is not None:
            current.warnings.append(message)


def clean_exit(error: BaseException) -> bool:
    """sys.exit(0) or a bare sys.exit() ends work that finished; it is not a failure."""
    return isinstance(error, SystemExit) and error.code in (0, None)


def clock() -> float:
    """The run's one clock, so intervals folded in line up with the spans around them."""
    collected = active()
    return collected.now() if collected is not None else time.perf_counter()


def active() -> Collector | None:
    """Return this task's buffer, or None outside an instrumented run."""
    return _active.get()


@contextmanager
def collecting(*, now: Callable[[], float] = time.perf_counter) -> Iterator[Collector]:
    """Isolate runs while letting copied worker contexts append to the same buffer."""
    collector = Collector(now=now)
    token = _active.set(collector)
    parent_token = _parent.set(None)
    handler = _RunLogHandler(collector)
    logger = logging.getLogger("immich_memories")
    logger.addHandler(handler)
    try:
        yield collector
    finally:
        logger.removeHandler(handler)
        _parent.reset(parent_token)
        _active.reset(token)


def open_at(root: Span, startup: Startup | None) -> None:
    """Move the root span back to process start and name the time before it `startup`.

    Each phase mark closes one `startup.<phase>` child where the previous one ended, and
    `startup.run_record` runs from the last mark to the root's old opening, so the children
    cover the startup span with no gap.
    """
    collector = active()
    if collector is None or startup is None or not startup.started < root.start:
        return
    opened = root.start
    root.start = startup.started
    whole = Span(
        next(collector._ids), "startup", root.span_id, startup.started, opened - startup.started
    )
    collector.spans.append(whole)
    token = _parent.set(whole)
    try:
        begin = startup.started
        for phase, ended in startup.marks:
            if begin <= ended <= opened:
                collector.interval(f"startup.{phase}", begin, ended - begin, None)
                begin = ended
        collector.interval("startup.run_record", begin, opened - begin, None)
    finally:
        _parent.reset(token)


@contextmanager
def span(name: str, *, items: int | None = None, **attributes: float) -> Iterator[Span]:
    """Measure one operation, retaining its exception and application frames on failure."""
    collector = active()
    now = collector.now if collector else time.perf_counter
    parent = _parent.get()
    measured = Span(
        next(collector._ids) if collector else 0,
        name,
        parent.span_id if parent else None,
        now(),
        items=items,
        attributes=attributes,
    )
    token = _parent.set(measured)
    watch = peak_memory.watch_open() if collector else None
    try:
        yield measured
    except BaseException as error:
        if clean_exit(error):
            raise
        measured.error = {
            "type": type(error).__name__,
            "message": redact_secrets(str(error)),
            "frames": [
                f"{frame.filename.split('immich_memories/')[-1]}:{frame.lineno}:{frame.name}"
                for frame in traceback.extract_tb(error.__traceback__)
                if "immich_memories/" in frame.filename
            ],
        }
        raise
    finally:
        measured.duration = max(0.0, now() - measured.start)
        if watch is not None:
            peak_memory.watch_close(watch)
            measured.peak_rss, measured.peak_tree_rss = watch.own, watch.tree
        _parent.reset(token)
        if collector is not None:
            collector.spans.append(measured)
