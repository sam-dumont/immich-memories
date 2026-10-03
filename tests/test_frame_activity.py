"""How much each half second of a playback changes, read off its index alone (#1949)."""

import shutil
import subprocess

import pytest

from immich_memories.processing.playback_keyframes import frame_activity

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

    activity = frame_activity(ranged(data, []))

    busy = [size for second, size in activity.bins if 7.0 <= second < 9.5]
    still = [size for second, size in activity.bins if second < 6.5 or second >= 10.5]
    assert busy and still
    # A 60-pixel box in a 640x360 frame; the riders on the June finish clips moved it 5-10x.
    assert min(busy) > 1.5 * max(still)


def test_a_long_clip_costs_its_index_and_no_frame(tmp_path):
    data = race(tmp_path / "long.mp4", seconds=240.0, busy=(140.0, 143.0))
    asked: list[tuple[int, int]] = []

    activity = frame_activity(ranged(data, asked))

    assert activity.bytes_read < 0.2 * len(data)
    head, index, *headers = asked
    assert all(length <= 16 for _start, length in headers), "box headers only; never a frame"
