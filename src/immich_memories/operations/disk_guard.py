"""Free-space preflight for the output and cache volumes.

A film that outgrows its volume mid-render is worse than one that never
started: it leaves a partial file and a confusing error deep in the encoder.
This checks the real filesystem before a byte is written, using the same
calibration `processing/rate_control.py` already measured its encoders
against, so the estimate is not a second, independently-guessed table.
"""

from __future__ import annotations

import math
import shutil
from dataclasses import dataclass
from pathlib import Path

# The two anchors `rate_control.py` measured on real 1080p60 footage: CRF 18
# ("high") at 4.6 Mbps, CRF 24 ("balanced"/"fast") at 1.6 Mbps. Interpolating
# (or extrapolating) linearly in log-bitrate against CRF reuses that same
# slope rather than inventing a second calibration.
_HIGH_CRF = 18
_HIGH_MBPS = 4.6
_BALANCED_CRF = 24
_BALANCED_MBPS = 1.6

# Audio track, container overhead, and headroom for a real estimate to run a
# little hot rather than a little short.
_ESTIMATE_MARGIN = 1.15

_WHAT_TO_DO = (
    "Run `immich-memories runs delete` to reclaim space, or enable upload so "
    "finished films are removed automatically."
)


def estimate_output_bytes(duration_seconds: float, crf: int) -> int:
    """Estimate a film's on-disk size from its duration and encoder CRF."""
    if duration_seconds <= 0:
        return 0
    slope = math.log(_BALANCED_MBPS / _HIGH_MBPS) / (_BALANCED_CRF - _HIGH_CRF)
    mbps = _HIGH_MBPS * math.exp(slope * (crf - _HIGH_CRF))
    bytes_per_second = mbps * 1_000_000 / 8
    return int(duration_seconds * bytes_per_second * _ESTIMATE_MARGIN)


@dataclass(frozen=True)
class VolumeSpace:
    """Free space on the volume backing one configured path."""

    label: str
    path: Path
    free_bytes: int

    @property
    def free_gb(self) -> float:
        return self.free_bytes / (1024**3)


def volume_space(label: str, path: Path) -> VolumeSpace | None:
    """Free space for the volume backing `path`, or None if it can't be read.

    Reads the nearest existing ancestor: a run's output directory is created
    just before this runs, and a fresh checkout's cache directory may not
    exist yet either, but both always have a parent that does.
    """
    probe = path
    while not probe.exists():
        parent = probe.parent
        if parent == probe:
            return None
        probe = parent
    try:
        usage = shutil.disk_usage(probe)
    except OSError:
        return None
    return VolumeSpace(label=label, path=path, free_bytes=usage.free)


class InsufficientDiskSpace(RuntimeError):
    """A film cannot fit on a configured volume; stop before rendering it."""


def low_space_warning(volume: VolumeSpace, *, min_free_gb: float) -> str | None:
    """A warning naming the volume, its free space, and what to do -- or None."""
    if volume.free_gb >= min_free_gb:
        return None
    return (
        f"Low disk space on {volume.label} ({volume.path}): {volume.free_gb:.1f} GB free, "
        f"below the {min_free_gb:.0f} GB warning threshold. {_WHAT_TO_DO}"
    )


def require_room_for_film(volume: VolumeSpace, *, estimated_bytes: int) -> None:
    """Fail early, naming the volume, the free space, and the film's estimate."""
    if volume.free_bytes >= estimated_bytes:
        return
    estimated_gb = estimated_bytes / (1024**3)
    raise InsufficientDiskSpace(
        f"Not enough free space on {volume.label} ({volume.path}) for this film: "
        f"{volume.free_gb:.1f} GB free, need about {estimated_gb:.1f} GB. {_WHAT_TO_DO}"
    )
