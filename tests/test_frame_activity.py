"""How much each half second of a playback changes, read off its index alone (#1949)."""

import shutil
import subprocess

import numpy as np
import pytest

from immich_memories.processing.playback_keyframes import PlaybackIndex

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def race(path, *, seconds: float, busy: tuple[float, float]) -> bytes:
    """A still road; a box crosses it only during `busy`. Keyframes every 2 s, with sound."""
    a, b = busy
    x = f"if(between(t\\,{a}\\,{b})\\,(t-{a})*80\\,if(lt(t\\,{a})\\,0\\,{(b - a) * 80}))"
    subprocess.run(  # noqa: S603 - fixed argv in a test
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", f"color=c=gray:s=640x360:r=30:d={seconds}",
            "-f", "lavfi", "-i", f"color=c=white:s=60x60:r=30:d={seconds}",
            "-f", "lavfi", "-i", f"sine=duration={seconds}",
            "-filter_complex", f"[0][1]overlay=x='{x}':y=150[v]",
            "-map", "[v]", "-map", "2", "-c:v", "libx264", "-g", "60", "-c:a", "aac",
            "-movflags", "+faststart", str(path),
        ],
        check=True,
    )  # fmt: skip
    return path.read_bytes()


def ranged(data: bytes, asked: list[tuple[int, int]]):
    def read(start: int, length: int) -> tuple[bytes, int]:
        asked.append((start, length))
        return data[start : start + length], len(data)

    return read


def test_activity_rises_where_the_box_crosses(tmp_path):
    data = race(tmp_path / "race.mp4", seconds=12.0, busy=(7.0, 10.0))

    activity = PlaybackIndex(ranged(data, [])).activity()

    busy = [size for second, size in activity if 7.0 <= second < 9.5]
    still = [size for second, size in activity if second < 6.5 or second >= 10.5]
    assert busy and still
    # A 60-pixel box in a 640x360 frame; the riders on the June finish clips moved it 5-10x.
    assert min(busy) > 1.5 * max(still)


def test_a_long_clip_costs_its_index_and_no_frame(tmp_path):
    data = race(tmp_path / "long.mp4", seconds=240.0, busy=(140.0, 143.0))
    asked: list[tuple[int, int]] = []

    index = PlaybackIndex(ranged(data, asked))
    index.activity()

    assert index.bytes_read < 0.2 * len(data)
    head, index, *headers = asked
    assert all(length <= 16 for _start, length in headers), "box headers only; never a frame"


def shout(path, *, seconds: float, loud: tuple[float, float]) -> bytes:
    """A still 4K-ish picture, silent except for a tone during `loud`."""
    a, b = loud
    subprocess.run(  # noqa: S603 - fixed argv in a test
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc2=s=1280x720:r=30:d={seconds}",
            "-f", "lavfi", "-i",
            f"aevalsrc='if(between(t\\,{a}\\,{b})\\,0.5*sin(2*PI*440*t)\\,0)':s=44100:d={seconds}",
            "-c:v", "libx264", "-b:v", "8M", "-g", "60", "-c:a", "aac",
            "-movflags", "+faststart", str(path),
        ],
        check=True,
    )  # fmt: skip
    return path.read_bytes()


def test_the_sound_of_a_span_costs_the_span_not_the_clip(tmp_path):
    data = shout(tmp_path / "shout.mp4", seconds=20.0, loud=(12.0, 13.0))
    asked: list[tuple[int, int]] = []

    index = PlaybackIndex(ranged(data, asked))
    pcm = index.audio(10.0, 15.0, workdir=tmp_path / "work")
    span = index.bytes_read

    assert pcm is not None and len(pcm) == pytest.approx(5 * 16000, rel=0.02)
    loud = np.abs(pcm[int(2.2 * 16000) : int(2.8 * 16000)]).mean()
    quiet = np.abs(pcm[: int(1.5 * 16000)]).mean()
    assert loud > 20 * max(quiet, 1e-6), "the tone sits 2 s into the span"
    # Five seconds (and the one before, for a line under way) of a 20 s clip.
    assert span < 0.4 * len(data)
