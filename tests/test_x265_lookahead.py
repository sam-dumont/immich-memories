"""libx265 keeps as many lookahead frames as the memory budget holds at the output size (#1527)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from immich_memories.processing import memory_budget
from immich_memories.processing.encoding_plan import EncodingPlan, HdrTransfer, OutputCodec
from immich_memories.processing.memory_budget import x265_lookahead
from immich_memories.processing.streaming_assembler import StreamingEncoder

GIB = 2**30
FOUR_K = 2160 * 3840
HD = 1080 * 1920


@pytest.mark.parametrize(
    ("gigabytes", "pixels", "frames"),
    [
        (2, FOUR_K, 5),
        (3, FOUR_K, 5),
        (4, FOUR_K, 10),
        (8, FOUR_K, None),
        (16, FOUR_K, None),
        (2, HD, None),
        (3, HD, None),
        (4, HD, None),
        (8, HD, None),
        (16, HD, None),
    ],
)
def test_the_lookahead_follows_the_budget_and_the_frame_size(gigabytes, pixels, frames):
    assert x265_lookahead(gigabytes * GIB, pixels=pixels) == frames


def test_unknown_memory_keeps_the_default():
    assert x265_lookahead(None, pixels=FOUR_K) is None


@pytest.fixture
def container(tmp_path, monkeypatch):
    """A cgroup limit read from a tmp file, below any real machine's RAM."""

    def limit(gigabytes: int) -> None:
        (tmp_path / "memory.max").write_text(f"{gigabytes * GIB}\n")
        monkeypatch.setattr(memory_budget, "_CGROUP", tmp_path)
        memory_budget.encode_lookahead.cache_clear()

    yield limit
    memory_budget.encode_lookahead.cache_clear()


def _started_encode(monkeypatch, tmp_path, encoder: str, width: int, height: int) -> list[str]:
    started: list[list[str]] = []

    def launch(cmd, **_kwargs):
        started.append(cmd)
        raise OSError("not started")

    # WHY: the ffmpeg process is the boundary; the test reads the command it is given.
    monkeypatch.setattr(subprocess, "Popen", launch)
    plan = EncodingPlan(
        OutputCodec.H265,
        encoder,
        ("-preset", "medium", "-crf", "20"),
        HdrTransfer.HLG,
        False,
        "yuv420p10le" if encoder == "libx265" else "p010le",
        "mp4",
    )
    with pytest.raises(OSError, match="not started"):
        StreamingEncoder(Path(tmp_path / "film.mp4"), width, height, 30, plan).start()
    return started[0]


def test_a_4k_software_encode_on_4_gb_carries_a_lookahead_of_10(tmp_path, monkeypatch, container):
    container(4)
    cmd = _started_encode(monkeypatch, tmp_path, "libx265", 2160, 3840)
    assert cmd[cmd.index("-x265-params") + 1] == "rc-lookahead=10"
    assert cmd.index("-x265-params") > cmd.index("libx265")


def test_a_1080p_encode_keeps_the_default_on_the_same_box(tmp_path, monkeypatch, container):
    container(4)
    cmd = _started_encode(monkeypatch, tmp_path, "libx265", 1080, 1920)
    assert "-x265-params" not in cmd


def test_a_hardware_encode_is_untouched(tmp_path, monkeypatch, container):
    container(2)
    cmd = _started_encode(monkeypatch, tmp_path, "hevc_videotoolbox", 2160, 3840)
    assert "-x265-params" not in cmd
    assert not any("rc-lookahead" in part for part in cmd)


def test_photo_clips_merge_the_lookahead_into_their_own_x265_params(container, monkeypatch):
    from immich_memories.photos import photo_pipeline

    container(3)

    # WHY: whether this machine has VideoToolbox decides the branch; the test takes libx265.
    class NoHardware:
        stdout = ""

    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: NoHardware())
    args = photo_pipeline._get_photo_encoder_args("smpte2084", (2160, 3840))
    params = args[args.index("-x265-params") + 1]
    assert params.startswith("hdr-opt=1:")
    assert params.endswith(":rc-lookahead=5")
