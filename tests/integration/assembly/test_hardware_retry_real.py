"""A film keeps every clip's picture after a hardware encoder fails mid-stream (#2345).

The software retry decodes the clips again into the same audio work dir. The first
attempt has already written those clips' WAVs; the retry must still decode them.
"""

from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from immich_memories.processing import streaming_assembler
from immich_memories.processing.assembly_config import (
    AssemblyClip,
    AssemblySettings,
    TransitionType,
    standalone_assembly_encoding_plan,
)
from immich_memories.processing.video_assembler import VideoAssembler
from tests.integration.conftest import ffprobe_json, requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]

WIDTH, HEIGHT, FPS, SECONDS = 160, 96, 30, 1
COLOURS = {"red": (255, 0, 0), "lime": (0, 255, 0), "blue": (0, 0, 255)}


def _clip(tmp_path: Path, colour: str) -> Path:
    path = tmp_path / f"{colour}.mp4"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
            f"color={colour}:s={WIDTH}x{HEIGHT}:r={FPS}:d={SECONDS}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={SECONDS}",
            "-c:v", "libx264", "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
        capture_output=True,
    )  # fmt: skip
    return path


class _HardwareEncoderFailingAfter:
    """Accepts some frames, then stops reading, as a crashed VAAPI/NVENC encoder does."""

    def __init__(self, frames: int) -> None:
        self._frames = frames

    def start(self) -> None:
        pass

    def write_frame(self, frame: np.ndarray) -> None:
        if self._frames == 0:
            raise streaming_assembler.StreamingEncoderWriteError("hardware encoder died")
        self._frames -= 1

    def finish(self) -> None:
        pass


@pytest.mark.feature("render.software-retry-keeps-picture")
def test_software_retry_keeps_the_picture_of_every_clip(tmp_path, monkeypatch, caplog):
    real_encoder = streaming_assembler.StreamingEncoder

    def encoder(output_path, width, height, fps, encoding_plan=None):
        if encoding_plan is not None and encoding_plan.encoder == "h264_vaapi":
            # Two clips decoded, their WAVs written, then the failure.
            return _HardwareEncoderFailingAfter(int(1.5 * FPS))
        return real_encoder(output_path, width, height, fps, encoding_plan=encoding_plan)

    # WHY: the hardware encoder is the boundary; no CI runner has a VAAPI device.
    monkeypatch.setattr(streaming_assembler, "StreamingEncoder", encoder)
    hardware = replace(standalone_assembly_encoding_plan(18), encoder="h264_vaapi", encoder_args=())
    settings = AssemblySettings(
        encoding_plan=hardware,
        target_resolution=(WIDTH, HEIGHT),
        transition=TransitionType.CUT,
        scale_mode="fit",
    )
    clips = [AssemblyClip(path=_clip(tmp_path, colour), duration=SECONDS) for colour in COLOURS]

    film = VideoAssembler(settings).assemble(clips, tmp_path / "film.mp4")

    assert "retrying" in caplog.text
    video = next(s for s in ffprobe_json(film)["streams"] if s["codec_type"] == "video")
    assert int(video["nb_frames"]) == len(COLOURS) * SECONDS * FPS
    pixels = np.frombuffer(
        subprocess.check_output(
            ["ffmpeg", "-v", "error", "-i", str(film), "-vf", "scale=1:1"]
            + ["-pix_fmt", "rgb24", "-f", "rawvideo", "-"]
        ),
        np.uint8,
    ).reshape(-1, 3)
    for index, rgb in enumerate(COLOURS.values()):
        middle = pixels[index * SECONDS * FPS + SECONDS * FPS // 2].astype(int)
        # Each clip shows its own primary, not black or a neighbour's: encoders round pure
        # colours differently (CI's libx264 gives lime as 215), so compare channels, not values.
        channel = int(np.argmax(rgb))
        assert int(np.argmax(middle)) == channel and middle[channel] > 150, (index, middle)
        assert np.delete(middle, channel).max() < 60, (index, middle)
    assert "Frame underrun" not in caplog.text
