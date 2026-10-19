"""A worker's decode still vouches for its film after the music remux copies the video (#2709).

With remote rendering and music, the app decoded the whole film a second time: the
music remux rewrote the file, so the worker's decode no longer matched its stamp.
The remux copies the video stream, and the decode check reads only that stream, so
identical video packets carry the decode across.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from immich_memories.processing import output_contract
from immich_memories.processing.encoding_plan import EncodingPlan, HdrTransfer, OutputCodec
from immich_memories.processing.output_contract import (
    carried_verification,
    validate_output,
    video_stream_digest,
)

PLAN = EncodingPlan(
    codec=OutputCodec.H264,
    encoder="libx264",
    encoder_args=(),
    target_transfer=HdrTransfer.NONE,
    tone_map_to_sdr=False,
    pixel_format="yuv420p",
    container="mp4",
)


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-v", "error", *args], check=True)  # noqa: S603, S607


@pytest.fixture
def film(tmp_path) -> Path:
    path = tmp_path / "film.mp4"
    _ffmpeg(
        "-f", "lavfi", "-i", "testsrc2=size=128x72:rate=30:duration=2",
        "-vf", "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
    )  # fmt: skip
    return path


def _remux_music(film: Path, *, video: list[str]) -> None:
    staged = film.with_name("film.music.mp4")
    _ffmpeg(
        "-i", str(film), "-f", "lavfi", "-i", "sine=frequency=330:duration=2",
        "-map", "0:v", "-map", "1:a", *video, "-c:a", "aac", "-shortest", str(staged),
    )  # fmt: skip
    os.replace(staged, film)


def test_a_copied_video_stream_keeps_the_decode_that_vouched_for_it(film, monkeypatch):
    worker = validate_output(film, PLAN)
    digest = video_stream_digest(film)
    assert digest is not None

    _remux_music(film, video=["-c:v", "copy"])
    carried = carried_verification(film, worker, digest)

    assert carried is not None
    assert carried.decoded_frames == worker.decoded_frames == 60

    def no_second_decode(*_args):
        raise AssertionError("the film was decoded again")

    # WHY: the full decode is the work under test; it must not run a second time.
    monkeypatch.setattr(output_contract, "_decode_video_stream", no_second_decode)
    assert validate_output(film, PLAN, verified=carried).decoded_frames == 60


def test_a_re_encoded_video_stream_is_decoded_again(film):
    worker = validate_output(film, PLAN)
    digest = video_stream_digest(film)

    _remux_music(film, video=["-c:v", "libx264", "-crf", "30"])

    assert carried_verification(film, worker, digest) is None


def test_without_an_earlier_decode_there_is_nothing_to_carry(film):
    assert carried_verification(film, None, "0,v,SHA256=00") is None
