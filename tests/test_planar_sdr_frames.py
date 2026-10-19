"""SDR video stays planar from decoder to encoder (#2687)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest

from immich_memories.processing.frame_preview import maybe_emit_preview
from immich_memories.processing.streaming_assembler import StreamingEncoder
from immich_memories.processing.streaming_frame_blender import FrameBlender
from immich_memories.processing.streaming_frame_decoder import FrameDecoder
from tests.integration.conftest import requires_ffmpeg

W, H = 64, 48


class _Sink:
    def __init__(self) -> None:
        self.frames: list[np.ndarray] = []

    def write_frame(self, frame: np.ndarray) -> None:
        self.frames.append(frame.copy())


def _planar(y: int, chroma: int = 128) -> np.ndarray:
    frame = np.empty(W * H * 3 // 2, dtype=np.uint8)
    frame[: W * H] = y
    frame[W * H :] = chroma
    return frame


@requires_ffmpeg
def test_the_decoder_hands_over_a_planar_frame_of_the_source_colour(tmp_path: Path) -> None:
    clip = tmp_path / "grey.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color=c=0x808080:s={W}x{H}:r=10:d=0.5",
         "-pix_fmt", "yuv420p", "-c:v", "libx264", str(clip)],
        check=True, capture_output=True,
    )  # fmt: skip

    frames = list(FrameDecoder(clip, width=W, height=H, fps=10, pix_fmt="yuv420p"))

    assert frames
    for frame in frames:
        assert frame.shape == (W * H * 3 // 2,)
        assert frame.dtype == np.uint8
        # The source Y of mid grey in limited range, untouched by any RGB round trip.
        assert abs(int(frame[: W * H].mean()) - 126) <= 2


def test_a_crossfade_between_planar_frames_blends_every_plane() -> None:
    sink = _Sink()
    blender = FrameBlender(sink, W, H, planar_sdr=True)
    a, b = _planar(40), _planar(200)

    blender.emit_crossfade(iter([a, a]), iter([b, b]), 2)

    assert [int(f[0]) for f in sink.frames] == [120, 200]
    assert all(f.shape == a.shape for f in sink.frames)


def test_a_missing_planar_frame_fades_from_limited_range_black() -> None:
    sink = _Sink()
    blender = FrameBlender(sink, W, H, planar_sdr=True)

    blender.emit_crossfade(iter([]), iter([_planar(116, 128)]), 1)

    assert int(sink.frames[0][0]) == 116
    sink = _Sink()
    FrameBlender(sink, W, H, planar_sdr=True).emit_crossfade(iter([_planar(116)]), iter([]), 1)
    assert int(sink.frames[0][0]) == 16  # alpha=1 lands on black: Y=16, not green


def test_a_planar_frame_becomes_a_preview() -> None:
    previews: list[bytes] = []

    maybe_emit_preview(_planar(128), 0.0, previews.append, False, H, W)

    assert previews
    assert previews[0].startswith(b"\xff\xd8")


def test_the_sdr_encoder_takes_planar_frames(monkeypatch, tmp_path: Path) -> None:
    seen: list[list[str]] = []

    def fake_popen(cmd, **_kwargs):  # noqa: ANN001
        seen.append(list(cmd))
        raise RuntimeError("stop")

    # WHY: the real FFmpeg process is the boundary; only its command line matters here.
    monkeypatch.setattr(
        "immich_memories.processing.streaming_assembler.subprocess.Popen", fake_popen
    )

    with pytest.raises(RuntimeError, match="stop"):
        StreamingEncoder(tmp_path / "o.mp4", W, H, 30).start()

    cmd = seen[0]
    assert cmd[cmd.index("-pix_fmt") + 1] == "yuv420p"
