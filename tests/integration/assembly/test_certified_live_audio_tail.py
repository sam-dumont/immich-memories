"""Complete Live video may finish before its independently decoded audio track."""

import json
import struct
import subprocess
from pathlib import Path

import numpy as np
import pytest

from immich_memories import generate_downloads as downloads
from immich_memories.processing import editorial_live_render as certified
from immich_memories.processing.live_material import LiveRenderMaterial, LiveSourceEntry
from tests.integration.assembly.test_certified_live_quantization import _certified_clip
from tests.integration.conftest import requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]


def _audio_tail_source(path: Path, *, color: str = "red", frequency: int = 440) -> Path:
    video, audio = path.with_suffix(".video.mov"), path.with_suffix(".wav")
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
            f"color=c={color}:size=160x120:rate=30", "-frames:v", "60",
            "-c:v", "libx264", "-bf", "0", "-pix_fmt", "yuv420p",
            "-video_track_timescale", "600", str(video),
        ], check=True,
    )  # fmt: skip
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-f", "lavfi", "-t", "2.4", "-i",
            f"sine=frequency={frequency}:sample_rate=48000", "-c:a", "pcm_s16le", str(audio),
        ], check=True,
    )  # fmt: skip
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-i", str(video), "-i", str(audio),
            "-c", "copy", "-video_track_timescale", "600", str(path),
        ], check=True,
    )  # fmt: skip
    return path


def _decode_streams(path):
    subprocess.run(
        ["ffmpeg", "-v", "error", "-xerror", "-i", str(path), "-map", "0:v:0",
         "-map", "0:a:0", "-f", "null", "-"], check=True, capture_output=True,
    )  # fmt: skip
    return json.loads(
        subprocess.check_output(
            ["ffprobe", "-v", "error", "-count_frames", "-show_streams", "-of", "json", str(path)]
        )
    )["streams"]


def test_complete_video_holds_its_final_frame_through_verified_audio_tail(tmp_path):
    source = _audio_tail_source(tmp_path / "companion.mov")
    material = LiveRenderMaterial((LiveSourceEntry("still", "video", 0.0, 0.0, 2.4),))

    merged = certified.render_certified_live(
        _certified_clip(material), [source], tmp_path,
        merge=downloads._try_merge_burst, hardware_enabled=False,
    )  # fmt: skip

    record = json.loads(merged.with_suffix(".json").read_text())
    timing = record["frame_quantization"]["sources"][0]
    proof = timing["audio_tail_hold"]
    assert proof["video_decoded_frames"] == proof["video_declared_frames"] == 60
    assert proof["video_end_seconds"] == 2.0
    assert proof["audio_end_seconds"] == 2.4
    assert proof["audio_decoded_samples"] == 115200
    assert proof["hold_seconds"] == pytest.approx(0.4)
    video, audio = _decode_streams(merged)
    assert int(video["nb_read_frames"]) == 72
    assert float(video["duration"]) == pytest.approx(2.4)
    assert float(audio["duration"]) == pytest.approx(2.4, abs=1 / 48000)
    assert record["frame_quantization"]["final_frame_hold"] is None


def test_first_segment_audio_tail_keeps_the_next_segment_at_its_certified_start(tmp_path):
    first = _audio_tail_source(tmp_path / "red.mov")
    second = _audio_tail_source(tmp_path / "blue.mov", color="blue", frequency=880)
    material = LiveRenderMaterial(
        (
            LiveSourceEntry("still-a", "video-a", 0.0, 0.0, 2.4),
            LiveSourceEntry("still-b", "video-b", 1.0, 0.0, 1.0),
        )
    )

    merged = certified.render_certified_live(
        _certified_clip(material), [first, second], tmp_path,
        merge=downloads._try_merge_burst, hardware_enabled=False,
    )  # fmt: skip

    # Independently decode every output frame. The first blue frame belongs at
    # 2.4 s, after 72 red frames; a final-only hold would move it 0.4 s earlier.
    pixels = subprocess.check_output([
        "ffmpeg", "-v", "error", "-xerror", "-i", str(merged),
        "-vf", "scale=1:1", "-pix_fmt", "rgb24", "-f", "rawvideo", "-",
    ])  # fmt: skip
    frames = [pixels[index : index + 3] for index in range(0, len(pixels), 3)]
    assert len(frames) == 102
    assert all(red > blue + 100 for red, _green, blue in frames[:72])
    assert all(blue > red + 100 for red, _green, blue in frames[72:])
    video, audio = _decode_streams(merged)
    assert float(video["duration"]) == pytest.approx(3.4)
    assert float(audio["duration"]) == pytest.approx(3.4, abs=1 / 48000)
    pcm = subprocess.check_output([
        "ffmpeg", "-v", "error", "-xerror", "-i", str(merged), "-map", "0:a:0",
        "-ac", "1", "-ar", "48000", "-f", "s16le", "-",
    ])  # fmt: skip
    samples = np.frombuffer(pcm, dtype="<i2")
    for start, expected in [(2.2, 440), (2.5, 880)]:
        window = samples[round(start * 48000) : round((start + 0.05) * 48000)]
        frequency = np.count_nonzero((window[:-1] <= 0) & (window[1:] > 0)) / 0.05
        assert frequency == pytest.approx(expected, abs=20)


def test_audio_tail_cannot_authorize_material_after_actual_audio_end(tmp_path):
    source = _audio_tail_source(tmp_path / "companion.mov")
    material = LiveRenderMaterial((LiveSourceEntry("still", "video", 0.0, 0.0, 2.5),))
    with pytest.raises(ValueError, match="exceeds actual video source"):
        certified.render_certified_live(
            _certified_clip(material), [source], tmp_path,
            merge=downloads._try_merge_burst, hardware_enabled=False,
        )  # fmt: skip


def test_decoded_audio_outside_its_visible_edit_cannot_authorize_a_hold(tmp_path):
    source = _audio_tail_source(tmp_path / "audio-edit.mov")
    data = bytearray(source.read_bytes())
    first_edit = data.index(b"elst")
    audio_edit = data.index(b"elst", first_edit + 4)
    movie = data.index(b"mvhd")
    assert data[audio_edit + 4] == 0
    timescale = struct.unpack_from(">I", data, movie + 16)[0]
    struct.pack_into(">I", data, audio_edit + 12, round(2.3 * timescale))
    source.write_bytes(data)
    material = LiveRenderMaterial((LiveSourceEntry("still", "video", 0.0, 0.0, 2.3005),))

    with pytest.raises(ValueError, match="exceeds actual video source"):
        certified.render_certified_live(
            _certified_clip(material), [source], tmp_path,
            merge=downloads._try_merge_burst, hardware_enabled=False,
        )  # fmt: skip


@pytest.mark.parametrize("invalid", ["missing-audio", "incomplete-video-edit"])
def test_audio_tail_needs_audio_and_every_declared_visible_video_sample(tmp_path, invalid):
    source = _audio_tail_source(tmp_path / "source.mov")
    if invalid == "missing-audio":
        target = tmp_path / "silent.mov"
        subprocess.run([
            "ffmpeg", "-v", "error", "-i", str(source), "-map", "0:v:0",
            "-c", "copy", str(target),
        ], check=True)  # fmt: skip
        source = target
    else:
        data = bytearray(source.read_bytes())
        edit, movie = data.index(b"elst"), data.index(b"mvhd")
        timescale = struct.unpack_from(">I", data, movie + 16)[0]
        struct.pack_into(">I", data, edit + 12, round(1.9 * timescale))
        source.write_bytes(data)
    material = LiveRenderMaterial((LiveSourceEntry("still", "video", 0.0, 0.0, 2.4),))

    with pytest.raises(ValueError, match="exceeds actual video source"):
        certified.render_certified_live(
            _certified_clip(material), [source], tmp_path,
            merge=downloads._try_merge_burst, hardware_enabled=False,
        )  # fmt: skip
