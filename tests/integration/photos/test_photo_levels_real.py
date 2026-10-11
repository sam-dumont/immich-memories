"""A photo without a gain map keeps its levels in the film (#2344).

A plain SDR JPEG is rendered through the generator's photo path, then measured as
decoded pixels: in an SDR film straight from the photo clip, in an HDR film after
the streaming assembler has placed it next to PQ video.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from immich_memories.config_loader import Config
from immich_memories.processing.encoding_plan import EncodingPlan, HdrTransfer, OutputCodec
from immich_memories.processing.hdr_utilities import check_zscale_available
from tests.integration.conftest import requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]

WIDTH, HEIGHT, FPS = 128, 96, 10
# Black, a mid grey and white of a grey card, as 8-bit sRGB.
GREY_CARD = (0, 128, 255)


def _grey_card(tmp_path: Path, level: int) -> Path:
    # WHY: a flat card makes the Ken Burns move and the blur bands invisible,
    # so the centre pixel measures the transfer alone.
    path = tmp_path / f"card_{level}.png"
    Image.new("RGB", (WIDTH * 2, HEIGHT * 2), (level, level, level)).save(path)
    return path


def _photo_clip(tmp_path: Path, level: int, *, codec: str):
    from immich_memories.generate import GenerationParams
    from immich_memories.generate_photos import render_photo_as_clip
    from immich_memories.processing.output_canvas import OutputCanvas
    from tests.conftest import make_clip

    work = tmp_path / f"{codec}_{level}"
    work.mkdir()
    params = GenerationParams(
        clips=[],
        output_path=work / "film.mp4",
        config=Config(
            hardware={"enabled": False},
            photos={"duration": 1},
            output={"codec": codec, "hdr_mode": "auto"},
        ),
        output_canvas=OutputCanvas(WIDTH, HEIGHT, "landscape"),
    )
    clip = render_photo_as_clip(
        make_clip(f"card-{level}"), params, work, source_path=_grey_card(work, level)
    )
    assert clip is not None
    return clip


def _centre_luma(path: Path, pix_fmt: str) -> int:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-frames:v", "1"]
        + ["-f", "rawvideo", "-pix_fmt", pix_fmt, "-"],
        capture_output=True,
        check=True,
        timeout=30,
    ).stdout
    dtype = np.uint16 if pix_fmt.endswith("10le") else np.uint8
    luma = np.frombuffer(raw, dtype)[: WIDTH * HEIGHT].reshape(HEIGHT, WIDTH)
    return int(np.median(luma[HEIGHT // 4 : 3 * HEIGHT // 4, WIDTH // 4 : 3 * WIDTH // 4]))


def _pq_code(nits: float) -> int:
    """The 10-bit TV-range PQ code value for an absolute luminance."""
    m1, m2, c1, c2, c3 = 0.1593017578125, 78.84375, 0.8359375, 18.8515625, 18.6875
    y = (nits / 10000) ** m1
    return round(64 + 876 * ((c1 + c2 * y) / (1 + c3 * y)) ** m2)


@pytest.mark.parametrize("level", GREY_CARD)
def test_an_sdr_film_keeps_the_photos_levels(tmp_path, level):
    clip = _photo_clip(tmp_path, level, codec="h264")

    expected = round(16 + 219 * level / 255)
    assert abs(_centre_luma(clip.path, "yuv420p") - expected) <= 2


def test_photo_white_lands_at_diffuse_white_in_an_hdr_film(tmp_path):
    from immich_memories.processing.streaming_assembler import assemble_streaming

    if not check_zscale_available():
        pytest.skip("an HDR film needs zscale")
    clip = _photo_clip(tmp_path, 255, codec="h265")
    film = tmp_path / "film.mp4"
    assemble_streaming(
        clips=[clip],
        transitions=[],
        output_path=film,
        width=WIDTH,
        height=HEIGHT,
        fps=FPS,
        fade_duration=0.0,
        encoding_plan=EncodingPlan(
            codec=OutputCodec.H265,
            encoder="libx265",
            encoder_args=("-crf", "4", "-preset", "ultrafast"),
            target_transfer=HdrTransfer.PQ,
            tone_map_to_sdr=False,
            pixel_format="yuv420p10le",
            container="mp4",
        ),
        scale_mode="black",
    )

    # WHY: SDR reference white belongs at 203 nits (ITU-R BT.2408) in a PQ film.
    assert abs(_centre_luma(film, "yuv420p10le") - _pq_code(203)) <= 4
