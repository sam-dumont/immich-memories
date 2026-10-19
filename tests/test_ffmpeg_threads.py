"""Every FFmpeg a render starts is sized from the CPU limit (#2687)."""

from __future__ import annotations

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
