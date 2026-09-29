"""Each assembly decode gets a bounded number of threads (#1527).

An FFmpeg decode left on its default takes one thread per core, and each thread
holds its own 4K frames: 1.2 GB per decode on an 18-core Mac, and a crossfade
runs two at once.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from immich_memories.processing import streaming_frame_decoder
from immich_memories.processing.memory_budget import decoder_threads

GIB = 2**30


@pytest.mark.parametrize(
    ("gigabytes", "cpus", "threads"),
    [(2, 4, 1), (3, 4, 1), (4, 4, 2), (8, 4, 4), (128, 18, 4), (16, 2, 2), (None, 18, 4)],
)
def test_one_decode_thread_per_two_gigabytes_capped_at_four(gigabytes, cpus, threads):
    memory = None if gigabytes is None else gigabytes * GIB
    assert decoder_threads(memory, cpus=cpus) == threads


def test_the_decode_is_started_with_bounded_threads(tmp_path, monkeypatch):
    started: list[list[str]] = []

    class Stopped:
        stdout = None

        def __init__(self, cmd, **_kwargs):
            started.append(cmd)
            raise OSError("not started")

    # WHY: the ffmpeg process is the boundary; the test reads the command it is given.
    monkeypatch.setattr(subprocess, "Popen", Stopped)
    decoder = streaming_frame_decoder.FrameDecoder(
        Path(tmp_path / "clip.mov"), width=2160, height=3840, fps=30, threads=2
    )
    with pytest.raises(OSError, match="not started"):
        next(iter(decoder))

    (cmd,) = started
    assert cmd[cmd.index("-threads") + 1] == "2"
    assert cmd.index("-threads") < cmd.index("-i")
