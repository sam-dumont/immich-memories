"""NAS Live intermediates fit the canvas and the actual encoder's color capabilities."""

import json
import subprocess
from pathlib import Path

import pytest

from immich_memories.config_loader import Config
from immich_memories.processing.hardware import detect_hardware_acceleration
from immich_memories.processing.live_photo_merger import build_merge_command

pytestmark = pytest.mark.integration


def _hdr_source(tmp_path: Path, size: str = "3840x2160", transfer: str = "smpte2084") -> Path:
    source = tmp_path / "hdr-source.mp4"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color=gray:s={size}:r=30",
            "-frames:v", "3", "-pix_fmt", "yuv420p10le", "-c:v", "libx265",
            "-preset", "ultrafast", "-x265-params",
            "pools=1:frame-threads=1:rc-lookahead=0:bframes=0:repeat-headers=1:"
            f"colorprim=bt2020:transfer={transfer}:colormatrix=bt2020nc",
            "-color_primaries", "bt2020", "-color_trc", transfer, "-colorspace", "bt2020nc",
            str(source),
        ],
        check=True, capture_output=True,
    )  # fmt: skip
    source_stream = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_streams",
        "-of", "json", str(source),
    ]))["streams"][0]  # fmt: skip
    assert source_stream["color_transfer"] == transfer
    assert source_stream["color_primaries"] == "bt2020"
    return source


@pytest.mark.parametrize(
    "size,transfer,expected",
    [("3840x2160", "smpte2084", (1920, 1080)), ("2160x3840", "arib-std-b67", (1080, 1920))],
)
def test_nas_hdr_live_intermediate_is_bounded_and_hardware_encoded(
    tmp_path: Path, size, transfer, expected
):
    source = _hdr_source(tmp_path, size, transfer)
    output = tmp_path / "merged.mp4"
    command = build_merge_command([source], [(0.0, 0.1)], output, config=Config(tier="nas"))
    subprocess.run(command, capture_output=True, check=True)
    stream = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
        "-show_streams", "-of", "json", str(output),
    ]))["streams"][0]  # fmt: skip
    assert (stream["width"], stream["height"]) == expected
    assert int(stream["nb_read_frames"]) == 3
    capabilities = detect_hardware_acceleration()
    encoder = command[command.index("-c:v") + 1]
    if capabilities.supports_h265_encode:
        assert encoder.startswith("hevc_")
        assert stream["color_transfer"] == transfer
    elif capabilities.supports_h264_encode:
        assert encoder.startswith("h264_")
        assert stream["color_transfer"] == "bt709"
    else:
        assert stream["color_transfer"] == transfer


def test_nas_download_binds_the_policy_and_reuses_the_certified_merge(tmp_path: Path):
    from types import SimpleNamespace

    from immich_memories.generate_downloads import download_clip
    from immich_memories.processing.editorial_live_render import RENDER_VERSION
    from immich_memories.processing.live_material import LiveRenderMaterial, LiveSourceEntry

    source = _hdr_source(tmp_path)
    material = LiveRenderMaterial((LiveSourceEntry("still", "video", 0.0, 0.0, 0.1),))
    clip = SimpleNamespace(
        asset=SimpleNamespace(id="still", live_photo_video_id="video"),
        duration_seconds=0.1,
        live_burst_still_ids=material.still_ids,
        live_burst_video_ids=material.video_ids,
        live_burst_trim_points=material.trim_points,
        live_burst_shutter_timestamps=material.shutter_timestamps,
        live_burst_material=material.as_dict(),
        editorial_live_manifest={
            "version": RENDER_VERSION,
            "material": material.as_dict(),
            "selected_interval": [0.0, 0.1],
        },
    )
    prefetched = {"video": SimpleNamespace(path=source)}
    config = Config(tier="nas")
    output = download_clip(
        None, None, clip, tmp_path, prefetched_burst_results=prefetched, config=config
    )
    assert output is not None
    stream = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_streams",
        "-of", "json", str(output),
    ]))["streams"][0]  # fmt: skip
    assert (stream["width"], stream["height"]) == (1920, 1080)
    before = output.stat().st_mtime_ns
    assert (
        download_clip(
            None, None, clip, tmp_path, prefetched_burst_results=prefetched, config=config
        )
        == output
    )
    assert output.stat().st_mtime_ns == before
    record = json.loads(output.with_suffix(".json").read_text())
    assert record["identity"]["source_policy"]["tier"] == "basic"
