"""The memory this process may use, and how many sources it prepares at once (#1527).

A NAS container usually runs under a Compose memory limit well below the box's RAM,
so the container's cgroup limit wins over physical RAM when it is lower.
"""

from __future__ import annotations

import functools
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

_CGROUP = Path("/sys/fs/cgroup")
_GIB = 2**30
# A 4K HDR photo encoder alone exceeds 2 GB. Reserve the parent process
# separately, then allow 3 GiB per source including its decoded photo.
_SOURCE_GIB_PER_WORKER = 3
_PARENT_RESERVE = _GIB
# The fixed default before auto; a config that sets the key can go higher.
_MOST_AUTO_WORKERS = 2
_MOST_DECODER_THREADS = 4
# libx265's rc-lookahead by budget in GB, for frames above 1080p (#1527). Measured on a
# synthetic 4K vertical 10-bit encode (medium, crf 20, frame-threads 1): 951 MB with no
# lookahead, 1700 MB at 5, 1961 MB at 10: about 52 MB a lookahead frame, so x265's own
# default of 20 comes to about 2.5 GB. Beside it run two clip decodes (about 0.5 GB each
# at the capped thread count) and Python (about 0.35 GB): 4K fits 6 GB at the default,
# 4 GB at 10 and, just, 3 GB at 5. None keeps x265's default.
_LOOKAHEAD_BY_GB: tuple[tuple[int, int | None], ...] = ((6, None), (4, 10), (0, 5))
# A default 1080p encode measured 811 MB, which every budget holds.
_ABOVE_1080P = 1920 * 1088
_FOUR_K = (3840, 2160)
_SOURCE_ENCODER_MEMORY: ContextVar[int | None] = ContextVar("source_encoder_memory", default=None)


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


def _cpu_quota(root: Path) -> int | None:
    try:
        values = (root / "cpu.max").read_text().split()
    except OSError:
        values = _legacy_cpu_quota(root)
    try:
        limit, interval = map(int, values)
    except ValueError:
        return None
    return (limit + interval - 1) // interval if limit > 0 and interval > 0 else None


def _legacy_cpu_quota(root: Path) -> list[str]:
    for directory in (root / "cpu", root / "cpu,cpuacct", root):
        try:
            return [
                (directory / "cpu.cfs_quota_us").read_text(),
                (directory / "cpu.cfs_period_us").read_text(),
            ]
        except OSError:
            continue
    return []


def available_cpus(cgroup_root: Path | None = None) -> int:
    """CPU capacity under affinity and cgroup bandwidth limits."""
    available = os.cpu_count() or 1
    if hasattr(os, "sched_getaffinity"):
        with suppress(OSError):
            available = len(os.sched_getaffinity(0))
    quota = _cpu_quota(cgroup_root or _CGROUP)
    return max(1, min(available or 1, quota)) if quota is not None else max(1, available or 1)


def memory_budget(
    cgroup_root: Path | None = None, *, physical: int | None = None
) -> MemoryBudget | None:
    """The container's memory limit when it is below physical RAM, else physical RAM."""
    physical = _physical_ram() if physical is None else physical
    limit = _cgroup_limit(cgroup_root or _CGROUP)
    if limit is not None and (physical is None or limit < physical):
        return MemoryBudget(limit, "container limit")
    return MemoryBudget(physical, "physical RAM") if physical else None


def _per_two_gigabytes(memory: int | None, *, cpus: int, most: int) -> int:
    # Memory is rounded to whole GB first: a "4 GB" NAS reports about 3.8 GiB once
    # the kernel takes its share, and it should still count as 4.
    ceiling = max(1, min(most, cpus))
    if memory is None:
        return ceiling
    return max(1, min(ceiling, round(memory / _GIB) // 2))


def prepare_workers(memory: int | None, *, cpus: int) -> int:
    """Reserve the parent, then allow 3 GiB per source, one to two workers."""
    ceiling = max(1, min(_MOST_AUTO_WORKERS, cpus))
    if memory is None:
        return ceiling
    available = max(0, memory - _PARENT_RESERVE)
    return max(1, min(ceiling, available // (_SOURCE_GIB_PER_WORKER * _GIB)))


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
    threads = decoder_threads(budget.size if budget else None, cpus=available_cpus())
    logger.info("Assembly decodes: %d thread(s) each", threads)
    return threads


def assembly_frame_read_ahead(width: int, height: int, *, encoder: str) -> bool:
    """Overlap reads on the measured HEVC VideoToolbox path when resources allow."""
    # M2/M5 improved, but NVENC was neutral on GTX 1070 and slower on T1000.
    if encoder != "hevc_videotoolbox":
        return False
    if width * height < 1920 * 1080 or available_cpus() < 2:
        return False
    budget = memory_budget()
    return budget is not None and budget.size >= 4 * _GIB


def source_prepare_workers(
    configured: int | Literal["auto"],
    *,
    cgroup_root: Path | None = None,
    cpus: int | None = None,
) -> tuple[int, str]:
    """How many sources to prepare at once, and the sentence that says why."""
    if configured != "auto":
        return configured, f"{configured} at a time (set in the config)"
    budget = memory_budget(cgroup_root)
    workers = prepare_workers(
        budget.size if budget else None, cpus=cpus or available_cpus(cgroup_root)
    )
    if budget is None:
        return workers, f"{workers} at a time (memory unknown)"
    return workers, f"{workers} at a time ({budget.size / _GIB:.1f} GB available, {budget.source})"


def x265_lookahead(memory: int | None, *, pixels: int) -> int | None:
    """libx265's rc-lookahead for this budget and frame size; None keeps x265's default."""
    if memory is None or pixels <= _ABOVE_1080P:
        return None
    gigabytes = memory // _GIB
    return next(frames for floor, frames in _LOOKAHEAD_BY_GB if gigabytes >= floor)


def encode_lookahead(width: int, height: int) -> int | None:
    """Lookahead for this encoder's share of memory and its output size."""
    memory = _SOURCE_ENCODER_MEMORY.get()
    if memory is None:
        budget = memory_budget()
        memory = budget.size if budget else None
    frames = x265_lookahead(memory, pixels=width * height)
    logger.info("libx265 lookahead at %dx%d: %s", width, height, _frames(frames))
    return frames


@contextmanager
def source_encoder_budget(workers: int) -> Iterator[None]:
    """Share encoder memory between source workers while reserving their parent."""
    budget = memory_budget()
    share = max(0, budget.size - _PARENT_RESERVE) // workers if budget else None
    token = _SOURCE_ENCODER_MEMORY.set(share)
    try:
        yield
    finally:
        _SOURCE_ENCODER_MEMORY.reset(token)


def lookahead_summary() -> str:
    """The 4K libx265 lookahead this budget gets, as preflight prints it."""
    return f"libx265 lookahead at 4K: {_frames(encode_lookahead(*_FOUR_K))}"


def _frames(frames: int | None) -> str:
    return "x265 default" if frames is None else f"{frames} frames"


# The smallest budget, in whole GB, that holds a 4K software HEVC film. With no lookahead
# the encoder alone measured 951 MB, beside two decodes (about 0.95 GB) and Python (about
# 0.35 GB): about 2.3 GB, and the smallest lookahead the rule above uses (5) needs about
# 3 GB. Below it, an automatic 4K film renders at 1080p (owner: "1080p only below the floor").
SOFTWARE_4K_FLOOR_GB = 3


def film_tier(tier: str, *, memory: int | None, hardware_hevc: bool, explicit: bool) -> str:
    """The resolution tier a film renders at: 4K drops to 1080p only when nothing else fits.

    An explicit request, a hardware HEVC encoder or an unknown budget keeps ``tier``.
    """
    if tier != "4k" or explicit or hardware_hevc or memory is None:
        return tier
    return "1080p" if round(memory / _GIB) < SOFTWARE_4K_FLOOR_GB else tier


def floor_sentence(memory: int) -> str:
    """Why a film renders at 1080p, as the run log and preflight say it."""
    return (
        f"4K needs about {SOFTWARE_4K_FLOOR_GB} GB for software HEVC; this box has "
        f"{memory / _GIB:.1f} GB, so the film renders at 1080p"
    )


def explicit_4k_warning(memory: int) -> str:
    """What a run set to 4K on purpose is told below the floor: kept, but it may not fit."""
    return (
        f"4K set explicitly: software HEVC needs about {SOFTWARE_4K_FLOOR_GB} GB, this box has "
        f"{memory / _GIB:.1f} GB, so the render may run out of memory; set resolution to auto "
        "or 1080p"
    )
