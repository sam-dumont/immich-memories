"""Reading ahead must not overwrite the frame the encoder is still using."""

import subprocess
import sys
import time
from contextlib import closing

import numpy as np

from immich_memories.processing.streaming_frame_decoder import FrameDecoder


def test_next_frame_is_read_while_the_consumer_retains_the_current_frame(tmp_path, monkeypatch):
    marker = tmp_path / "second-frame-written"
    size = 512 * 512 * 3
    child = (
        "import pathlib,sys,time\n"
        f"size={size}\n"
        "for value in [17,29,41]:\n"
        " sys.stdout.buffer.write(bytes([value])*size);sys.stdout.buffer.flush()\n"
        f" if value==29:pathlib.Path({str(marker)!r}).touch()\n"
        "time.sleep(30)\n"
    )
    real_popen = subprocess.Popen
    spawned = []

    def start(_cmd, **kwargs):
        process = real_popen([sys.executable, "-c", child], **kwargs)
        spawned.append(process)
        return process

    # WHY: Replace only the producer's WRITE boundary. Its real pipe cannot hold
    # a whole second frame: the marker proves a reader drained it in the meantime.
    monkeypatch.setattr(subprocess, "Popen", start)
    decoder = FrameDecoder(tmp_path / "source.mp4", 512, 512, 30)
    try:
        with closing(decoder.iter_borrowed_frames(read_ahead=True)) as frames:
            first = next(frames)
            deadline = time.monotonic() + 5
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert marker.exists(), "next frame stayed blocked behind the consumer"
            assert np.all(first == 17)
            second = next(frames)
            assert np.all(second == 29)
            assert not second.flags.writeable
    finally:
        for process in spawned:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
