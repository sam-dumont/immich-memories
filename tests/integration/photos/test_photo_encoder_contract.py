"""Real photo encoding preserves the selected codec, transfer, cadence and canvas."""

from __future__ import annotations

import json
import subprocess

import pytest

from immich_memories.config_loader import Config
from immich_memories.config_models_render import PhotoConfig
from immich_memories.photos.encoding import photo_encoding_plan
from immich_memories.photos.photo_pipeline import render_single_photo
from immich_memories.processing.encoding_plan import HdrTransfer
from immich_memories.processing.hdr_utilities import check_zscale_available
from tests.conftest import make_asset
from tests.integration.conftest import requires_ffmpeg
from tests.test_photo_render import _gain_mapped_photo, _sdr_photo

pytestmark = [pytest.mark.integration, requires_ffmpeg]


@pytest.mark.parametrize("source", [_sdr_photo, _gain_mapped_photo])
@pytest.mark.parametrize("hardware", [True, False])
def test_nas_photo_obeys_its_real_encoder_contract(tmp_path, source, hardware):
    config = Config(tier="nas", hardware={"enabled": hardware})
    plan = photo_encoding_plan(
        config, transfer=HdrTransfer.PQ if check_zscale_available() else HdrTransfer.NONE
    )
    clip = render_single_photo(
        make_asset("synthetic-photo"),
        PhotoConfig(duration=1),
        128,
        192,
        tmp_path,
        None,
        fps=10,
        source_path=source(tmp_path),
        encoding_plan=plan,
    )
    assert clip is not None
    stream = json.loads(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-count_frames",
                "-select_streams",
                "v:0",
                "-show_streams",
                "-of",
                "json",
                str(clip.path),
            ]
        )
    )["streams"][0]
    assert stream["codec_name"] == ("hevc" if plan.hdr else "h264")
    assert (stream["width"], stream["height"]) == (128, 192)
    assert int(stream["nb_read_frames"]) == 10
    assert float(stream["duration"]) == pytest.approx(1, abs=0.001)
    assert stream["pix_fmt"] == ("yuv420p10le" if plan.hdr else "yuv420p")
    assert stream["color_transfer"] == ("smpte2084" if plan.hdr else "bt709")
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(clip.path), "-f", "null", "-"], check=True)
