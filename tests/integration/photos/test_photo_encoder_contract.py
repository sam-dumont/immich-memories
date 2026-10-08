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
    config = Config(tier="basic", hardware={"enabled": hardware})
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


@pytest.mark.parametrize(
    ("source", "codec", "hdr_mode", "override", "expected"),
    [
        (_sdr_photo, "h265", "auto", None, "h264"),
        (_gain_mapped_photo, "h265", "auto", None, "hevc"),
        (_gain_mapped_photo, "h265", "sdr", None, "h264"),
        (_gain_mapped_photo, "h264", "auto", "h265", "hevc"),
        (_gain_mapped_photo, "h265", "auto", "mp4", "h264"),
    ],
)
def test_source_and_film_choose_photo_intermediate(
    tmp_path, source, codec, hdr_mode, override, expected
):
    from immich_memories.generate import GenerationParams
    from immich_memories.generate_photos import render_photo_as_clip
    from immich_memories.processing.output_canvas import OutputCanvas
    from tests.conftest import make_clip

    if not check_zscale_available():
        pytest.skip("HDR conversion requires zscale")
    params = GenerationParams(
        clips=[],
        output_path=tmp_path / "film.mp4",
        config=Config(
            hardware={"enabled": False},
            photos={"duration": 1},
            output={"codec": codec, "hdr_mode": hdr_mode},
        ),
        output_format=override,
        output_canvas=OutputCanvas(128, 192, "portrait"),
    )
    clip = render_photo_as_clip(make_clip("photo"), params, tmp_path, source_path=source(tmp_path))
    assert clip is not None
    stream = json.loads(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_streams",
                "-of",
                "json",
                str(clip.path),
            ]
        )
    )["streams"][0]
    assert stream["codec_name"] == expected
    assert stream["color_transfer"] == ("smpte2084" if expected == "hevc" else "bt709")
    assert (stream["width"], stream["height"]) == (128, 192)
    assert float(stream["duration"]) == pytest.approx(1, abs=0.001)
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(clip.path), "-f", "null", "-"], check=True)


def _frame_stats(path, conversion="null"):
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-vf",
            f"{conversion},signalstats,metadata=print:file=-",
            "-frames:v",
            "1",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return {
        key: float(value)
        for line in result.stdout.splitlines()
        if "=" in line
        for key, value in [line.split("=", 1)]
        if key in {"lavfi.signalstats.YAVG", "lavfi.signalstats.SATAVG"}
    }


def test_sdr_photo_keeps_brightness_and_saturation_without_hevc(tmp_path, test_photo_landscape):
    from immich_memories.processing.hardware import HWAccelCapabilities
    from immich_memories.processing.hdr_utilities import get_hdr_conversion_filter

    if not check_zscale_available():
        pytest.skip("comparison with the former PQ intermediate requires zscale")
    clips = []
    for label, plan in [
        ("pq", photo_encoding_plan(transfer=HdrTransfer.PQ, capabilities=HWAccelCapabilities())),
        ("sdr", photo_encoding_plan(transfer=HdrTransfer.NONE, capabilities=HWAccelCapabilities())),
    ]:
        work = tmp_path / label
        work.mkdir()
        clip = render_single_photo(
            make_asset("same-source"),
            PhotoConfig(duration=1),
            192,
            128,
            work,
            None,
            fps=10,
            source_path=test_photo_landscape,
            encoding_plan=plan,
        )
        assert clip is not None
        clips.append(clip.path)
    before = _frame_stats(
        clips[0], get_hdr_conversion_filter("pq", "sdr", required=True).lstrip(",")
    )
    after = _frame_stats(clips[1])

    assert set(before) == {"lavfi.signalstats.YAVG", "lavfi.signalstats.SATAVG"}
    assert after == pytest.approx(before, rel=0.01)
