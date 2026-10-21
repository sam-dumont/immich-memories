"""A stills film comes out of the assembler at exactly its planned length (#2785).

Stills are made the way a run makes them, on a pool of preparing threads, and
assembled with fades and cuts. One still is a second short of its slot, as a
still whose move lost frames would be: the film still has every planned frame.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pytest

from immich_memories.photos.photo_pipeline import _stream_render_to_mp4
from immich_memories.photos.renderer import KenBurnsParams
from immich_memories.processing.assembly_config import AssemblyClip
from immich_memories.processing.encoding_plan import (
    EncodingPlan,
    HdrTransfer,
    OutputCodec,
)
from immich_memories.processing.streaming_assembler import assemble_streaming

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs FFmpeg")

FPS, WIDTH, HEIGHT, FADE = 10, 160, 96, 0.3
PLAN = EncodingPlan(
    codec=OutputCodec.H264,
    encoder="libx264",
    encoder_args=("-preset", "ultrafast", "-crf", "28"),
    target_transfer=HdrTransfer.NONE,
    tone_map_to_sdr=False,
    pixel_format="yuv420p",
    container="mp4",
)
# (slot seconds, seconds the still's file actually holds)
STILLS = [(1.5, 1.5), (2.0, 2.0), (1.5, 0.5), (2.0, 2.0)]
TRANSITIONS = ["fade", "cut", "fade"]


def _frame_count(path: Path) -> int:
    out = subprocess.run(  # noqa: S603, S607
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets"]
        + ["-show_entries", "stream=nb_read_packets", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    ).stdout
    return int(json.loads(out)["streams"][0]["nb_read_packets"])


def _still(tmp_path: Path, index: int) -> AssemblyClip:
    slot, held = STILLS[index]
    rng = np.random.default_rng(index)
    picture = (rng.random((120, 90, 3)) * 255).astype(np.uint8)
    path = tmp_path / f"still_{index}.mp4"
    params = KenBurnsParams(zoom_end=1.1, fps=FPS, duration=held)
    _stream_render_to_mp4(picture, params, path, WIDTH, HEIGHT, encoding_plan=PLAN)
    return AssemblyClip(path=path, duration=slot, asset_id=f"still-{index}", is_photo=True)


def test_a_stills_film_keeps_every_planned_frame(tmp_path):
    with ThreadPoolExecutor(2, thread_name_prefix="prepare") as pool:
        clips = list(pool.map(lambda index: _still(tmp_path, index), range(len(STILLS))))
    output = tmp_path / "film.mp4"

    assemble_streaming(
        clips=clips,
        transitions=TRANSITIONS,
        output_path=output,
        width=WIDTH,
        height=HEIGHT,
        fps=FPS,
        fade_duration=FADE,
        encoding_plan=PLAN,
    )

    fade_frames = int(FADE * FPS)
    planned = sum(int(slot * FPS) for slot, _held in STILLS) - fade_frames * TRANSITIONS.count(
        "fade"
    )
    assert _frame_count(clips[2].path) == 5
    assert _frame_count(output) == planned
