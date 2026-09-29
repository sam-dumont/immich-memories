"""The memory this process may use, and how many sources it prepares at once (#1527).

A NAS container usually runs under a Compose memory limit well below the box's RAM,
so the container's cgroup limit wins over physical RAM when it is lower.
"""

from __future__ import annotations

import functools
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

_CGROUP = Path("/sys/fs/cgroup")
_GIB = 2**30
# One photo at 4K peaks near 1.2 GB with its ffmpeg encode (synthetic, #1569),
# so each preparation worker gets 2 GB.
_GIB_PER_WORKER = 2
# The fixed default before auto; a config that sets the key can go higher.
_MOST_AUTO_WORKERS = 2
_MOST_DECODER_THREADS = 4


@dataclass(frozen=True)
class MemoryBudget:
    size: int
    source: Literal["container limit", "physical RAM"]


def _cgroup_limit(root: Path) -> int | None:
    # cgroup v2, then v1. "max" (v2) and v1's near-2**63 sentinel both mean no limit;
    # the sentinel is dropped by the comparison with physical RAM.
    for name in ("memory.max", "memory/memory.limit_in_bytes"):
        try:
            text = (root / name).read_text().strip()
        except OSError:
            continue
        return int(text) if text.isdigit() else None
    return None


def _physical_ram() -> int | None:
    try:
        return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    except (ValueError, OSError, AttributeError):
        return None


def _cpus() -> int:
    if hasattr(os, "sched_getaffinity"):
        return len(os.sched_getaffinity(0))
    return os.cpu_count() or 1


def memory_budget(
    cgroup_root: Path = _CGROUP, *, physical: int | None = None
) -> MemoryBudget | None:
    """The container's memory limit when it is below physical RAM, else physical RAM."""
    physical = _physical_ram() if physical is None else physical
    limit = _cgroup_limit(cgroup_root)
    if limit is not None and (physical is None or limit < physical):
        return MemoryBudget(limit, "container limit")
    return MemoryBudget(physical, "physical RAM") if physical else None


def _per_two_gigabytes(memory: int | None, *, cpus: int, most: int) -> int:
    # Memory is rounded to whole GB first: a "4 GB" NAS reports about 3.8 GiB once
    # the kernel takes its share, and it should still count as 4.
    ceiling = max(1, min(most, cpus))
    if memory is None:
        return ceiling
    return max(1, min(ceiling, round(memory / _GIB) // _GIB_PER_WORKER))


def prepare_workers(memory: int | None, *, cpus: int) -> int:
    """One worker per 2 GB, at least one, at most two and never more than the CPUs."""
    return _per_two_gigabytes(memory, cpus=cpus, most=_MOST_AUTO_WORKERS)


def decoder_threads(memory: int | None, *, cpus: int) -> int:
    """Threads for each FFmpeg decode feeding the assembly: one per 2 GB, 1 to 4.

    FFmpeg's default is one per core, and each holds its own frames: a 4K HEVC
    decode measured 1199 MB at 18 threads, 565 MB at 4 and 479 MB at 2, in the
    same wall time, because the blur fill, not the decode, sets the pace.
    """
    return _per_two_gigabytes(memory, cpus=cpus, most=_MOST_DECODER_THREADS)


@functools.cache
def assembly_decoder_threads() -> int:
    """`decoder_threads` for this process's memory budget, read once."""
    budget = memory_budget()
    threads = decoder_threads(budget.size if budget else None, cpus=_cpus())
    logger.info("Assembly decodes: %d thread(s) each", threads)
    return threads


def source_prepare_workers(
    configured: int | Literal["auto"],
    *,
    cgroup_root: Path = _CGROUP,
    cpus: int | None = None,
) -> tuple[int, str]:
    """How many sources to prepare at once, and the sentence that says why."""
    if configured != "auto":
        return configured, f"{configured} at a time (set in the config)"
    budget = memory_budget(cgroup_root)
    workers = prepare_workers(budget.size if budget else None, cpus=cpus or _cpus())
    if budget is None:
        return workers, f"{workers} at a time (memory unknown)"
    return workers, f"{workers} at a time ({budget.size / _GIB:.1f} GB available, {budget.source})"
