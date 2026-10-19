"""A still is rendered in the HDR film's transfer once its videos settle it (#2709).

Gain-mapped stills came out as PQ and SDR stills as SDR, and an HLG film converted
every frame of them with zscale. Stills are prepared after the videos, so the film's
transfer is known then, unless the stills themselves could still swing it: a
gain-mapped still votes PQ, and which a still is only shows once it is decoded.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from immich_memories import generate_clips
from immich_memories.api.models import AssetType
from immich_memories.config.loader import Config
from immich_memories.generate import GenerationParams
from immich_memories.processing.assembly_config import AssemblyClip
from immich_memories.processing.encoding_plan import HdrTransfer
from tests.conftest import make_clip

_TRC = {"hlg": "arib-std-b67", "pq": "smpte2084"}


def _photo(asset_id: str):
    clip = make_clip(asset_id)
    clip.asset.type = AssetType.IMAGE
    return clip


def _video_file(path: Path, transfer: str) -> Path:
    subprocess.run(  # noqa: S603, S607 - a fixture clip with a known transfer
        [
            "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=64x36:r=30:d=1",
            "-vf", f"setparams=color_primaries=bt2020:color_trc={_TRC[transfer]}"
            ":colorspace=bt2020nc",
            "-c:v", "libx264", "-pix_fmt", "yuv420p10le", str(path),
        ],
        check=True,
    )  # fmt: skip
    return path


def _transfers(tmp_path, monkeypatch, videos: list[str], stills: int, codec: str):
    clips = [make_clip(f"video-{i}") for i in range(len(videos))]
    clips += [_photo(f"still-{i}") for i in range(stills)]
    files = {
        f"video-{i}": _video_file(tmp_path / f"video-{i}.mp4", transfer)
        for i, transfer in enumerate(videos)
    }
    seen: list[HdrTransfer | None] = []

    def rendered(extraction, clip, _progress, _name, **_kwargs):
        if clip.asset.type == AssetType.IMAGE:
            seen.append(extraction.params.photo_transfer)
            return AssemblyClip(path=tmp_path / "still.mp4", duration=1.0, is_photo=True)
        return AssemblyClip(path=files[clip.asset.id], duration=1.0, asset_id=clip.asset.id)

    # WHY: preparing a source downloads and encodes it; the transfer the stills are
    # prepared in is what is under test.
    monkeypatch.setattr(generate_clips, "_rendered_clip", rendered)
    config = Config(hardware={"enabled": False}, output={"codec": codec})
    params = GenerationParams(clips=clips, output_path=tmp_path / "film.mp4", config=config)
    generate_clips.extract_clips(params, None, tmp_path, scratch_dir=tmp_path)
    return seen


@pytest.mark.parametrize(
    ("videos", "stills", "codec", "expected"),
    [
        # Two HLG videos outvote one still whatever it turns out to be.
        (["hlg", "hlg"], 1, "h265", HdrTransfer.HLG),
        (["hlg", "hlg", "hlg"], 3, "h265", HdrTransfer.HLG),
        # Two gain-mapped stills would outvote the one HLG video: not settled yet.
        (["hlg"], 2, "h265", None),
        # PQ videos in the majority keep the film PQ either way.
        (["pq", "pq", "hlg"], 1, "h265", HdrTransfer.PQ),
        # An H.264 film is SDR: stills keep their own conversion, once on the picture.
        (["hlg", "hlg"], 1, "h264", None),
    ],
)
def test_stills_follow_the_transfer_their_videos_settle(
    tmp_path, monkeypatch, videos, stills, codec, expected
):
    assert _transfers(tmp_path, monkeypatch, videos, stills, codec) == [expected] * stills
