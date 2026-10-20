"""A finished film's freed buffers go back to the system instead of staying in malloc arenas."""

import ctypes
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from immich_memories_render_worker.jobs import release_freed_heap


def _resident_megabytes() -> int:
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) // 1024
    raise AssertionError("no VmRSS line")


def test_the_heap_trim_reports_whether_the_c_library_offers_it():
    assert release_freed_heap() is hasattr(ctypes.CDLL(None), "malloc_trim")


@pytest.mark.skipif(not Path("/proc/self/status").exists(), reason="reads Linux RSS")
def test_freed_frame_buffers_go_back_to_the_system():
    """Each thread's freed frames stay in its malloc arena until trimmed: +0.13 GB a film."""
    survivors = []
    lock = threading.Lock()
    # Frames, tiles and other small buffers interleave, as on a render's thread pools.
    sizes = (1080 * 1920 * 3, 256 * 256 * 3, 9_000_000, 4_000_000, 256 * 256 * 3)

    def film_frames(seed: int) -> None:
        frames = []
        for i in range(60):
            frame = bytearray(sizes[(seed + i) % len(sizes)])
            frame[::4096] = b"\1" * len(frame[::4096])
            frames = [*frames[-5:], frame]
        with lock:
            # A small live object on top of each arena keeps it from shrinking on its own.
            survivors.append(bytearray(64 * 1024))

    with ThreadPoolExecutor(16) as pool:
        list(pool.map(film_frames, range(64)))
    held = _resident_megabytes()

    released = release_freed_heap()

    assert released is True
    assert held - _resident_megabytes() > 100
