"""A still fills the film's own canvas, whatever its size (#2708).

The stills pass prepared its stills for a canvas voted by the stills alone, so a portrait
photo in a portrait film became a landscape clip with a blur fill, fitted again into the
portrait film. The odd sizes that produced (1215 px) also broke the one-pass colour
conversion of a still in an HDR film, which then converted every frame instead.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from immich_memories import generate_clips
from immich_memories.api.models import AssetType
from immich_memories.config.loader import Config
from immich_memories.config.models.render import PhotoConfig
from immich_memories.generate import GenerationParams
from immich_memories.generate_photos import render_photo_as_clip
from immich_memories.photos.photo_pipeline import render_single_photo
from immich_memories.processing.assembly_config import AssemblyClip
from immich_memories.processing.encoding_plan import EncodingPlan, HdrTransfer, OutputCodec
from immich_memories.processing.hdr_utilities import check_zscale_available
from tests.conftest import make_asset, make_clip
from tests.integration.conftest import requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]


def _size(path: Path) -> tuple[int, int]:
    stream = json.loads(
        subprocess.check_output(  # noqa: S603, S607 - our own clip, fixed argv
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_streams",
                "-of",
                "json",
                str(path),
            ]
        )  # fmt: skip
    )["streams"][0]
    return stream["width"], stream["height"]


def _portrait_video(path: Path) -> Path:
    subprocess.run(  # noqa: S603, S607 - a portrait clip the film's rate is read from
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=s=72x128:r=30:d=1",
            str(path),
        ],
        check=True,
    )
    return path


def test_a_portrait_still_in_a_portrait_film_is_prepared_like_a_single_pass_render(
    tmp_path,
    monkeypatch,
):
    photo = tmp_path / "portrait.jpg"
    Image.new("RGB", (300, 400), "orange").save(photo, "JPEG")
    still = make_clip("still", width=300, height=400)
    still.asset.type = AssetType.IMAGE
    landscape_still = make_clip("still-wide", width=400, height=300)
    landscape_still.asset.type = AssetType.IMAGE
    videos = [make_clip(f"video-{n}", width=1080, height=1920) for n in range(3)]
    clips = [still, *videos, landscape_still]
    video = _portrait_video(tmp_path / "video.mp4")
    config = Config(output={"resolution": "720p"}, photos={"duration": 1.0})

    def rendered(extraction, clip, _progress, _name, **_kwargs):
        if clip.asset.type == AssetType.IMAGE:
            # The real still render, for the parameters its pass hands it.
            return render_photo_as_clip(
                clip, extraction.params, extraction.output_dir, source_path=photo
            )
        return AssemblyClip(path=video, duration=1.0, asset_id=clip.asset.id)

    # WHY: preparing a source starts with a download from Immich; the still is local here
    # and the videos are a fixture clip.
    monkeypatch.setattr(generate_clips, "_rendered_clip", rendered)
    params = GenerationParams(clips=clips, output_path=tmp_path / "film.mp4", config=config)
    prepared = generate_clips.extract_clips(params, None, tmp_path, scratch_dir=tmp_path)

    single = tmp_path / "single"
    single.mkdir()
    one_pass = render_photo_as_clip(
        still,
        GenerationParams(clips=clips, output_path=tmp_path / "one.mp4", config=config),
        single,
        source_path=photo,
    )
    assert one_pass is not None
    # The stills tie (one portrait, one landscape); the film is portrait, and so are they.
    assert _size(one_pass.path) == (720, 1280)
    assert [_size(clip.path) for clip in prepared if clip.is_photo] == [(720, 1280)] * 2


def test_an_odd_sized_still_in_an_hdr_film_is_converted_once(tmp_path, caplog):
    if not check_zscale_available():
        pytest.skip("an HDR film needs zscale")
    photo = tmp_path / "odd.png"
    # Both sides odd and below the source cap, so the conversion sees them as they are.
    Image.new("RGB", (81, 121), (200, 120, 40)).save(photo)
    plan = EncodingPlan(
        codec=OutputCodec.H265,
        encoder="libx265",
        encoder_args=("-crf", "28", "-preset", "ultrafast"),
        target_transfer=HdrTransfer.HLG,
        tone_map_to_sdr=False,
        pixel_format="yuv420p10le",
        container="mp4",
    )

    with caplog.at_level(logging.WARNING, logger="immich_memories.photos.photo_pipeline"):
        clip = render_single_photo(
            make_asset("odd-still"),
            PhotoConfig(duration=1.0),
            72,
            128,
            tmp_path,
            None,
            fps=10,
            source_path=photo,
            encoding_plan=plan,
        )

    assert clip is not None
    assert _size(clip.path) == (72, 128)
    assert "Converting the still once failed" not in caplog.text
