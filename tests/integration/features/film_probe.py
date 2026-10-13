"""What a finished film sounds and looks like: loudness over a stretch, and colour in a frame."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


def loudness(
    path: Path, start: float = 0.0, end: float | None = None, *, tone: int | None = None
) -> tuple[float, float]:
    """Mean and peak volume (dBFS) of the film's sound between two instants (-91 is silence).

    `tone` keeps only a narrow band around that frequency, to hear one source under another.
    """
    window = ["-ss", f"{start:.3f}"] + (["-to", f"{end:.3f}"] if end is not None else [])
    band = f"bandpass=f={tone}:width_type=q:w=8,bandpass=f={tone}:width_type=q:w=8," if tone else ""
    probe = subprocess.run(  # noqa: S603 -- fixed ffmpeg argv
        [
            "ffmpeg",
            "-hide_banner",
            *window,
            "-i",
            str(path),
            "-af",
            f"{band}volumedetect",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stderr
    mean = re.search(r"mean_volume: (-?[\d.]+|-inf) dB", probe)
    peak = re.search(r"max_volume: (-?[\d.]+|-inf) dB", probe)
    assert mean and peak, probe[-2000:]

    def level(found: re.Match[str]) -> float:
        return -91.0 if found.group(1) == "-inf" else float(found.group(1))

    return level(mean), level(peak)


def grey_frame(path: Path, at_seconds: float, *, band: str = "iw:ih:0:0") -> bytes:
    """The frame at `at_seconds`, cropped to `band` (an FFmpeg crop), small and in grey."""
    frame = subprocess.run(  # noqa: S603 -- fixed ffmpeg argv
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            f"{at_seconds:.3f}",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            f"crop={band},scale=160:90,format=gray",
            "-f",
            "rawvideo",
            "-",
        ],
        capture_output=True,
        check=True,
    ).stdout
    assert frame, f"no frame at {at_seconds}s in {path.name}"
    return frame


def luma_difference(first: bytes, second: bytes) -> float:
    """Mean absolute difference (0-255) between two grey frames of one size."""
    assert len(first) == len(second)
    return sum(abs(x - y) for x, y in zip(first, second, strict=True)) / len(first)


def differing_columns(first: bytes, second: bytes, *, width: int = 160) -> float:
    """The share of the frame's width, from the left, that holds pixels the two frames differ on.

    A caption drawn over one of two otherwise identical frames shows up as how far it reaches.
    Two encodes of the same pictures still differ by a stray pixel here and there, so a pixel
    counts only beside another that differs too: letters are strokes, encoder noise is not.
    """
    height = len(first) // width
    differs = {
        (x, y)
        for y in range(height)
        for x in range(width)
        if abs(first[y * width + x] - second[y * width + x]) > 24
    }
    columns = [x for x, y in differs if {(x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)} & differs]
    return (max(columns) + 1) / width if columns else 0.0


def video_stream(path: Path) -> dict[str, str]:
    """The film's video stream as ffprobe names it: codec, pixel format, transfer, primaries."""
    probe = subprocess.run(  # noqa: S603 -- fixed ffprobe argv
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,pix_fmt,color_transfer,color_primaries",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(probe.stdout)["streams"][0]


def luma_levels(path: Path, at_seconds: float, *, convert: str = "") -> tuple[float, int]:
    """Mean and peak luma code of the frame at `at_seconds`, at the film's own bit depth.

    `convert` is an FFmpeg filter run first, e.g. `format=yuv420p` to read a photo in video range.
    """
    # A still image has one frame and no clock to seek on.
    seek = ["-ss", f"{at_seconds:.3f}"] if at_seconds else []
    chain = f"{convert}," if convert else ""
    stats = subprocess.run(  # noqa: S603 -- fixed ffmpeg argv
        ["ffmpeg", "-hide_banner", *seek, "-i", str(path), "-frames:v", "1"]
        + ["-vf", f"{chain}signalstats,metadata=print:file=-", "-f", "null", "-"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    found = dict(line.split("=", 1) for line in stats.splitlines() if "=" in line)
    return float(found["lavfi.signalstats.YAVG"]), int(found["lavfi.signalstats.YMAX"])


def warm_side(path: Path, at_seconds: float | None = None, *, band: str = "iw:ih:0:0") -> float:
    """How much warmer (red over blue) the left half of a frame is than its right half.

    Positive when the warm side is on the left. A picture turned upside down or mirrored
    flips the sign: the fixture's rain window has a yellow sign on one side.
    `band` is an FFmpeg crop of the frame first; `at_seconds` None reads a still image.
    """
    seek = [] if at_seconds is None else ["-ss", f"{at_seconds:.3f}"]
    frame = subprocess.run(  # noqa: S603 -- fixed ffmpeg argv
        ["ffmpeg", "-v", "error", *seek, "-i", str(path), "-frames:v", "1",
         "-vf", f"crop={band},scale=64:16", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip
    assert frame, f"no frame in {path.name}"
    warmth = [frame[i] - frame[i + 2] for i in range(0, len(frame), 3)]
    left = [w for index, w in enumerate(warmth) if index % 64 < 32]
    right = [w for index, w in enumerate(warmth) if index % 64 >= 32]
    return (sum(left) - sum(right)) / len(left)


def luma_percentile(path: Path, at_seconds: float, percent: float) -> float:
    """The luma code (8-bit) that `percent` % of the frame at `at_seconds` stays at or under.

    A decoded frame's single brightest pixel is no measure of the picture's range: lossy
    coding rings at a hard white edge, so a source held at 235 decodes a few codes above
    it there. A high percentile reads where the picture itself sits.
    """
    import numpy as np

    plane = subprocess.run(  # noqa: S603 -- fixed ffmpeg argv
        ["ffmpeg", "-v", "error", "-ss", f"{at_seconds:.3f}", "-i", str(path), "-frames:v", "1"]
        + ["-vf", "extractplanes=y", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True,
        check=True,
    ).stdout
    assert plane, f"no frame at {at_seconds}s in {path.name}"
    return float(np.percentile(np.frombuffer(plane, np.uint8), percent))
