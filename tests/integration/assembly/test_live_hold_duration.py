"""A certified subframe hold keeps its cadence through the MP4 muxer."""

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from immich_memories.config_models import HardwareAccelConfig
from immich_memories.config_models_render import OutputConfig
from immich_memories.processing.editorial_live_render import RENDER_VERSION, extract_certified_live
from immich_memories.processing.live_material import LiveRenderMaterial, LiveSourceEntry

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "rate,source_frames,output_frames,duration",
    [("30", 59, 60, 2.0), ("60", 119, 120, 2.0), ("30000/1001", 59, 60, 2.002)],
)
def test_certified_hold_keeps_all_frames_at_the_declared_cadence(
    tmp_path: Path, rate, source_frames, output_frames, duration
):
    source = tmp_path / "short.mp4"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size=160x120:rate={rate}",
            "-frames:v", str(source_frames), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source),
        ],
        check=True,
    )  # fmt: skip
    material = LiveRenderMaterial((LiveSourceEntry("still", "video", 0.0, 0.0, 2.0),))
    clip = SimpleNamespace(
        asset=SimpleNamespace(id="still", live_photo_video_id="video"),
        duration_seconds=2.0,
        live_burst_still_ids=material.still_ids,
        live_burst_video_ids=material.video_ids,
        live_burst_trim_points=material.trim_points,
        live_burst_shutter_timestamps=material.shutter_timestamps,
        live_burst_material=material.as_dict(),
        editorial_live_manifest={
            "version": RENDER_VERSION,
            "material": material.as_dict(),
            "selected_interval": [0.0, 2.0],
        },
    )

    def rounded_extract(_source, *, output_path, **_kwargs):
        # WHY: isolate the encoder boundary's permitted one-frame shortfall.
        # The hold itself uses real FFmpeg and its output is independently probed.
        shutil.copyfile(source, output_path)
        return output_path

    output, nominal = extract_certified_live(
        clip, source, tmp_path, extract=rounded_extract,
        config=SimpleNamespace(hardware=HardwareAccelConfig(enabled=False), output=OutputConfig()),
    )  # fmt: skip
    stream = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
        "-show_streams", "-of", "json", str(output),
    ]))["streams"][0]  # fmt: skip
    assert nominal == 2.0
    assert float(stream["duration"]) == duration
    assert stream["avg_frame_rate"] == (rate if "/" in rate else rate + "/1")
    assert int(stream["nb_read_frames"]) == output_frames
    record = json.loads(output.with_suffix(".json").read_text())
    assert record["frame_quantization"]["final_frame_hold"]["target_frames"] == output_frames
