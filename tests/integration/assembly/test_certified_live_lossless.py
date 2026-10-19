"""A certified Live clip reaches the film without a lossy step of its own (#2692).

The merge and the certified cut used to be encoded lossily, so a Live clip was
compressed three times. Both are lossless now; these tests render the same Live
Photo the old way and the new way and compare the frame counts, the records and
the decoded frames.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from immich_memories import generate_downloads as downloads
from immich_memories.api.models import AssetType, VideoClipInfo
from immich_memories.config.models.render import OutputConfig
from immich_memories.config.models.resources import HardwareAccelConfig
from immich_memories.processing import editorial_live_render as certified
from immich_memories.processing import live_photo_merger
from immich_memories.processing.clips import extract_clip
from immich_memories.processing.encoding_plan import (
    EncodingRequest,
    HdrMode,
    OutputCodec,
    resolve_encoding_plan,
)
from immich_memories.processing.hardware import HWAccelCapabilities
from immich_memories.processing.live_material import LiveRenderMaterial, LiveSourceEntry
from tests.conftest import make_asset
from tests.integration.conftest import requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]

SIZE = (320, 240)
# Record fields that name bytes or the encoder; every other field must not move.
_BYTES_AND_ENCODER = {"output_sha256", "input_sha256", "merged_sha256", "encoder"}


def _companion(path: Path, seconds: str) -> Path:
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", f"testsrc2=size={SIZE[0]}x{SIZE[1]}:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
            "-t", seconds, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-video_track_timescale", "600", str(path),
        ],
        check=True,
    )  # fmt: skip
    return path


def _clip(material: LiveRenderMaterial, interval: list[float]) -> VideoClipInfo:
    asset = make_asset(material.still_ids[0], duration=None)
    asset.type = AssetType.IMAGE
    asset.live_photo_video_id = material.video_ids[0]
    return VideoClipInfo(
        asset=asset,
        duration_seconds=material.duration_seconds,
        live_burst_still_ids=list(material.still_ids),
        live_burst_video_ids=list(material.video_ids),
        live_burst_trim_points=list(material.trim_points),
        live_burst_shutter_timestamps=list(material.shutter_timestamps),
        live_burst_material=material.as_dict(),
        editorial_live_manifest={
            "version": certified.RENDER_VERSION,
            "material": material.as_dict(),
            "selected_interval": interval,
        },
    )


def _previous_release_plan(*, is_hdr, hardware_enabled=True, config=None, input_transfer=None):
    """The plan merges had before #2692: software x264 at CRF 18 on a machine without hardware."""
    del is_hdr, hardware_enabled, config, input_transfer
    return resolve_encoding_plan(
        EncodingRequest(OutputCodec.H264, HdrMode.SDR, False, "fast", 18, "mp4", "strict"),
        HWAccelCapabilities(),
        input_has_hdr=False,
    )


def _render(tmp_path: Path, monkeypatch, *, previous: bool) -> tuple[Path, Path, Path]:
    out = tmp_path / ("previous" if previous else "lossless")
    out.mkdir()
    material = LiveRenderMaterial(
        (
            LiveSourceEntry("still-a", "video-a", 0.0, 0.0, 2.94),
            LiveSourceEntry("still-b", "video-b", 1.0, 0.4855, 2.94),
        )
    )
    paths = [_companion(out / f"{video}.mov", "3") for video in material.video_ids]
    clip = _clip(material, [0.5, 4.5])
    extract = extract_clip
    if previous:
        # WHY: rebuilds the previous release's two lossy encodes, the reference.
        monkeypatch.setattr(live_photo_merger, "burst_encoding_plan", _previous_release_plan)

        def extract(*args, **kwargs):
            return extract_clip(*args, **{**kwargs, "lossless": False})

    merged = certified.render_certified_live(
        clip, paths, out, merge=downloads._try_merge_burst, hardware_enabled=False
    )
    config = SimpleNamespace(
        tier="gpu", hardware=HardwareAccelConfig(enabled=False), output=OutputConfig()
    )
    segment, _nominal = certified.extract_certified_live(
        clip, merged, out, extract=extract, config=config
    )
    monkeypatch.undo()
    return merged, segment, out


def _frames(path: Path) -> np.ndarray:
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        check=True,
        capture_output=True,
        timeout=60,
    )
    return np.frombuffer(result.stdout, np.uint8).reshape(-1, SIZE[1], SIZE[0], 3)


def _without_bytes(value):
    if isinstance(value, dict):
        return {k: _without_bytes(v) for k, v in value.items() if k not in _BYTES_AND_ENCODER}
    if isinstance(value, list):
        return [_without_bytes(v) for v in value]
    return value


def _record(path: Path) -> dict:
    return _without_bytes(json.loads(path.with_suffix(".json").read_text()))


def test_the_lossless_live_keeps_its_frames_holds_and_records(tmp_path, monkeypatch):
    old_merge, old_segment, _ = _render(tmp_path, monkeypatch, previous=True)
    new_merge, new_segment, _ = _render(tmp_path, monkeypatch, previous=False)

    old_record, new_record = _record(old_merge), _record(new_merge)
    old_record.pop("identity")
    new_record.pop("identity")
    assert new_record == old_record
    assert _record(new_segment)["frame_quantization"] == _record(old_segment)["frame_quantization"]
    for old, new in ((old_merge, new_merge), (old_segment, new_segment)):
        before, after = _frames(old), _frames(new)
        assert len(after) == len(before)
        mse = np.mean((after.astype(np.float64) - before.astype(np.float64)) ** 2)
        # The same pictures, less the previous release's compression: its two encodes
        # left testsrc2's fine detail at about 38 dB.
        assert 10 * np.log10(255**2 / mse) > 35


def test_the_certified_cut_is_an_exact_copy_of_the_merged_frames(tmp_path, monkeypatch):
    """With both steps lossless, the cut holds the merge's own pixels: the film's encode
    is the only lossy step left."""
    merged, segment, _ = _render(tmp_path, monkeypatch, previous=False)

    whole, cut = _frames(merged), _frames(segment)
    first = round(0.5 * 30)
    np.testing.assert_array_equal(cut, whole[first : first + len(cut)])
