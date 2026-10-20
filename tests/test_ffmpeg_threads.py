"""Every FFmpeg a render starts is sized from the CPU limit (#2687)."""

from __future__ import annotations

import sys

from immich_memories.processing.ffmpeg_threads import with_cpu_threads
from immich_memories.processing.memory_budget import assembly_decoder_threads


def test_the_filter_graph_the_input_and_the_output_get_the_limit():
    cmd = with_cpu_threads(["ffmpeg", "-y", "-i", "in.mp4", "-c:v", "libx264", "out.mp4"], cpus=2)

    assert cmd == [
        "ffmpeg", "-filter_threads", "2", "-filter_complex_threads", "2",
        "-y", "-threads", "2", "-i", "in.mp4", "-c:v", "libx264", "-threads", "2", "out.mp4",
    ]  # fmt: skip


def test_a_count_the_caller_chose_stays():
    cmd = with_cpu_threads(
        ["ffmpeg", "-threads", "1", "-i", "a.mp4", "-threads", "3", "out.mp4"], cpus=8
    )

    assert cmd.count("-threads") == 2
    assert cmd[cmd.index("-threads") + 1] == "1"
    assert cmd[cmd.index("out.mp4") - 1] == "3"


def test_every_input_gets_its_own_decoder_count():
    cmd = with_cpu_threads(["ffmpeg", "-i", "a.mp4", "-i", "b.wav", "out.mp4"], cpus=4)

    assert [cmd[i - 2 : i] for i, t in enumerate(cmd) if t == "-i"] == [
        ["-threads", "4"],
        ["-threads", "4"],
    ]


def test_a_pipe_output_is_an_output():
    cmd = with_cpu_threads(["ffmpeg", "-f", "rawvideo", "-i", "pipe:0", "-f", "null", "-"], cpus=3)

    assert cmd[-3:] == ["-threads", "3", "-"]
    assert cmd.count("-threads") == 2


def test_one_cpu_means_one_thread():
    assert "0" not in with_cpu_threads(["ffmpeg", "-i", "a.mp4", "o.mp4"], cpus=0)


def test_two_crossfade_decoders_share_the_limit(monkeypatch):
    # WHY: the container's CPU limit is the boundary; two decoders run during a fade.
    monkeypatch.setattr("immich_memories.processing.memory_budget.available_cpus", lambda: 4)
    assembly_decoder_threads.cache_clear()
    try:
        assert assembly_decoder_threads() * 2 <= 4
    finally:
        assembly_decoder_threads.cache_clear()


def test_the_streaming_encoder_is_sized_from_the_limit(monkeypatch, tmp_path):
    from immich_memories.processing.streaming_assembler import StreamingEncoder

    seen: list[list[str]] = []

    def fake_popen(cmd, **_kwargs):
        seen.append(list(cmd))
        raise RuntimeError("stop")

    # WHY: FFmpeg itself is the boundary; the command line is what is under test.
    monkeypatch.setattr(
        "immich_memories.processing.streaming_assembler.subprocess.Popen", fake_popen
    )
    monkeypatch.setattr("immich_memories.processing.ffmpeg_threads.available_cpus", lambda: 3)

    try:
        StreamingEncoder(tmp_path / "o.mp4", 64, 48, 30).start()
    except RuntimeError:
        pass

    cmd = seen[0]
    assert cmd[cmd.index("-filter_threads") + 1] == "3"
    assert cmd[cmd.index("-threads") + 1] == "3"


def test_opencv_threads_follow_the_limit(monkeypatch):
    import cv2

    calls: list[int] = []
    # WHY: OpenCV's global pool is the boundary; record instead of changing it for other tests.
    monkeypatch.setattr(cv2, "setNumThreads", calls.append)

    from immich_memories.processing.ffmpeg_threads import limit_opencv_threads

    limit_opencv_threads(2)
    limit_opencv_threads(0)

    assert calls == [2, 1]


def test_the_encoder_pool_stays_inside_what_libx265_accepts():
    cmd = with_cpu_threads(["ffmpeg", "-i", "a.mp4", "-c:v", "libx265", "o.mp4"], cpus=32)

    assert cmd[cmd.index("o.mp4") - 1] == "16"
    assert cmd[cmd.index("-i") - 1] == "32"


_POOL_VARIABLES = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")


def test_openmp_and_blas_pools_take_the_limit_unless_the_operator_set_one():
    from immich_memories.processing.ffmpeg_threads import limit_native_pools

    environ = {"OPENBLAS_NUM_THREADS": "1"}
    limit_native_pools(environ, cpus=3)

    assert environ == {"OMP_NUM_THREADS": "3", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "3"}


def test_importing_the_app_sizes_torch_and_blas_pools_from_the_limit():
    """torch, NumPy and OpenCV read these once, as they load: by default one thread per host core."""
    import json
    import os
    import subprocess
    import sys

    probe = (
        "import json, os, sys, immich_memories\n"
        "from immich_memories.processing.memory_budget import available_cpus\n"
        "sizes = {name: os.environ.get(name) for name in sys.argv[1:]}\n"
        "try:\n"
        "    import torch\n"
        "    sizes['torch'] = str(torch.get_num_threads())\n"
        "except ImportError:\n"
        "    pass\n"
        "print(json.dumps({'cpus': str(available_cpus()), 'sizes': sizes}))\n"
    )
    env = {key: value for key, value in os.environ.items() if key not in _POOL_VARIABLES}
    result = subprocess.run(
        [sys.executable, "-c", probe, *_POOL_VARIABLES],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    report = json.loads(result.stdout.strip().splitlines()[-1])

    assert set(report["sizes"].values()) == {report["cpus"]}


class _RecordingTorch:
    """The one torch call the limit makes, recorded; the real torch is an optional extra."""

    def __init__(self) -> None:
        self.threads: list[int] = []

    def set_num_threads(self, count: int) -> None:
        self.threads.append(count)


def _fake_torch(monkeypatch) -> _RecordingTorch:
    torch = _RecordingTorch()
    # WHY: torch is an optional extra the unit run does not install; this records its pool size.
    monkeypatch.setitem(sys.modules, "torch", torch)
    # WHY: a fake 3-CPU container limit, below any host this suite runs on.
    monkeypatch.setattr("immich_memories.processing.ffmpeg_threads.available_cpus", lambda: 3)
    return torch


def test_torch_takes_the_limit_when_nobody_set_a_count(monkeypatch):
    from immich_memories.processing.ffmpeg_threads import limit_torch_threads

    torch = _fake_torch(monkeypatch)
    monkeypatch.delenv("OMP_NUM_THREADS", raising=False)

    limit_torch_threads()

    assert torch.threads == [3]


def test_torch_takes_the_operator_count(monkeypatch):
    from immich_memories.processing.ffmpeg_threads import limit_torch_threads

    torch = _fake_torch(monkeypatch)
    monkeypatch.setenv("OMP_NUM_THREADS", "2")

    limit_torch_threads()

    assert torch.threads == [2]


def test_demucs_sizes_torch_before_it_loads_its_model(monkeypatch):
    import types

    from immich_memories.audio.generators.demucs_local import DemucsLocalBackend

    torch = _fake_torch(monkeypatch)
    monkeypatch.delenv("OMP_NUM_THREADS", raising=False)
    loaded: list[int] = []
    pretrained = types.ModuleType("demucs.pretrained")
    pretrained.get_model = lambda _name: loaded.append(len(torch.threads)) or object()  # type: ignore[attr-defined]
    # WHY: the Demucs weights are a download; only the order of the two calls matters here.
    monkeypatch.setitem(sys.modules, "demucs", types.ModuleType("demucs"))
    monkeypatch.setitem(sys.modules, "demucs.pretrained", pretrained)

    DemucsLocalBackend(device="cpu")._load_model()

    assert torch.threads == [3]
    assert loaded == [1]  # the pool was sized before the model loaded
