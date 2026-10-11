"""A caption still reaches the frame when its font or image path holds ':' or an apostrophe (#2348).

Both paths sit inside the decoder's filter graph, which FFmpeg parses twice: once as a
graph and once as the filter's options. A Windows drive letter or a home folder with an
apostrophe in its name broke every caption, and with it the clip's decode.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import pytest

from immich_memories.processing.clip_caption import ClipCaption, caption_font_path
from immich_memories.processing.streaming_frame_decoder import FrameDecoder
from tests.integration.conftest import requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]


@pytest.fixture
def odd_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "it's a:folder"
    folder.mkdir()
    return folder


@pytest.fixture
def grey_clip(tmp_path: Path) -> Path:
    out = tmp_path / "grey.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=gray:size=320x180:rate=10:duration=1",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)],
        check=True,
        capture_output=True,
    )  # fmt: skip
    return out


def _frame(clip: Path, caption: ClipCaption | None, font: str | None) -> np.ndarray:
    decoder = FrameDecoder(clip, width=320, height=180, fps=10, caption=caption, caption_font=font)
    frame = next(iter(decoder), None)
    assert frame is not None, "the decoder produced no frame"
    return frame.copy()


@pytest.mark.parametrize(
    "place", ["Nice, France", "Ηράκλειο, Ελλάδα"], ids=["drawtext", "image-overlay"]
)
@pytest.mark.feature("render.media-small-fixes")
def test_a_caption_draws_from_a_path_with_a_colon_and_an_apostrophe(
    grey_clip: Path, odd_dir: Path, monkeypatch, place: str
) -> None:
    bundled = caption_font_path()
    assert bundled is not None
    font = odd_dir / "font.ttf"
    shutil.copyfile(bundled, font)
    # WHY: the caption image is written to the private temp dir; this puts it under the odd path.
    monkeypatch.setattr(tempfile, "tempdir", str(odd_dir))

    plain = _frame(grey_clip, None, str(font))
    drawn = _frame(grey_clip, ClipCaption(place=place), str(font))

    assert np.any(plain != drawn), "the caption drew nothing"
