#!/usr/bin/env python3
"""CPU time of one render of a fixed, generic cut: before/after numbers for render changes.

The cut is four 1080p SDR clips (one at 60 fps, three at 30), and one gain-mapped photo,
joined with crossfades into an SDR 1080p film. It generates its own media, so the same
command gives comparable numbers on any checkout:

    PYTHONPATH=<other checkout>/src uv run python scripts/measure_render_cpu.py

CPU is this process plus every FFmpeg it spawned (user + system), the number a container
CPU limit is billed against. Wall time is printed for context only.
"""

from __future__ import annotations

import argparse
import io
import json
import resource
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from PIL import Image

CLIPS = (("a", 30, 4), ("b", 60, 3), ("c", 30, 4), ("d", 30, 3))
PHOTO_SECONDS = 4.0


def _make_clip(path: Path, rate: int, seconds: int) -> None:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
         f"testsrc2=s=1920x1080:r={rate}:d={seconds}", "-f", "lavfi", "-i",
         f"sine=d={seconds}", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-shortest", str(path)],
        check=True, capture_output=True,
    )  # fmt: skip


def _make_gain_mapped_photo(path: Path) -> None:
    """A 4:3 JPEG with an appended gain map, the layout `prepare_photo_source` reads."""
    width, height = 2880, 2160
    x = np.linspace(0, 1, width)[None, :]
    y = np.linspace(0, 1, height)[:, None]
    rng = np.random.default_rng(7)
    base = np.stack([x + 0 * y, y + 0 * x, 0.5 * (x + y)], axis=-1)
    base = np.clip(base * 200 + rng.normal(0, 4, base.shape), 0, 255).astype(np.uint8)
    primary = io.BytesIO()
    Image.fromarray(base).save(primary, "JPEG", quality=92, comment=b"hdrgm:Version=1.0")
    gain = Image.fromarray((x * 255 + 0 * y).astype(np.uint8))
    gain_bytes = io.BytesIO()
    gain.save(gain_bytes, "JPEG", quality=90)
    path.write_bytes(primary.getvalue() + gain_bytes.getvalue())


def _asset(asset_id: str):
    from immich_memories.api.models import Asset, AssetType

    now = datetime.now(tz=UTC)
    return Asset(
        id=asset_id, type=AssetType.IMAGE, fileCreatedAt=now, fileModifiedAt=now, updatedAt=now,
        originalFileName="photo.jpg",
    )  # fmt: skip


def _cpu() -> float:
    own = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    return own.ru_utime + own.ru_stime + children.ru_utime + children.ru_stime


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", type=Path, help="reuse/create the fixture media here")
    args = parser.parse_args()

    import immich_memories
    from immich_memories.config.models.render import PhotoConfig
    from immich_memories.photos.photo_pipeline import render_single_photo
    from immich_memories.processing.assembly_config import (
        AssemblyClip,
        AssemblySettings,
        TransitionType,
        standalone_assembly_encoding_plan,
    )
    from immich_memories.processing.ffmpeg_prober import film_frame_rate, probe_rate
    from immich_memories.processing.probe_cache import ProbeCache
    from immich_memories.processing.video_assembler import VideoAssembler

    root = args.keep or Path(tempfile.mkdtemp(prefix="render-cpu-"))
    root.mkdir(parents=True, exist_ok=True)
    clips: list[AssemblyClip] = []
    for name, rate, seconds in CLIPS:
        path = root / f"{name}.mp4"
        if not path.exists():
            _make_clip(path, rate, seconds)
        clips.append(AssemblyClip(path=path, duration=float(seconds), asset_id=name))
    photo = root / "photo.jpg"
    if not photo.exists():
        _make_gain_mapped_photo(photo)

    cache = ProbeCache()
    rate = film_frame_rate(clips, lambda p: probe_rate(cache, p))
    work = root / "work"
    work.mkdir(exist_ok=True)
    output = root / "film.mp4"

    started, cpu_before = time.monotonic(), _cpu()
    still = render_single_photo(
        _asset("photo"), PhotoConfig(duration=PHOTO_SECONDS), 1920, 1080, work, None,
        fps=rate, source_path=photo, scale_mode="blur",
    )  # fmt: skip
    assert still is not None, "the photo did not render"
    clips.insert(2, still)
    settings = AssemblySettings(
        encoding_plan=standalone_assembly_encoding_plan(28),
        target_resolution=(1920, 1080),
        auto_resolution=False,
        transition=TransitionType.CROSSFADE,
        transition_duration=0.3,
        normalize_clip_audio=False,
    )
    VideoAssembler(settings).assemble(clips, output)
    print(
        json.dumps(
            {
                "source": str(Path(immich_memories.__file__).parent),
                "film_frame_rate": rate,
                "cpu_seconds": round(_cpu() - cpu_before, 2),
                "wall_seconds": round(time.monotonic() - started, 2),
                "film": str(output),
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
