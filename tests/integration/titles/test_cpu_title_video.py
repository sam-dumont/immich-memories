"""CPU title fallback keeps the film's fades and media contract."""

import json
import subprocess
from pathlib import Path

import numpy as np
import pytest

from immich_memories.titles.generator import TitleScreenConfig
from immich_memories.titles.rendering_service import RenderingService
from immich_memories.titles.styles import TitleStyle
from tests.integration.conftest import requires_ffmpeg
from tests.integration.titles.conftest import extract_frame_rgb, ffprobe_stream, has_audio_stream

pytestmark = [pytest.mark.integration, requires_ffmpeg, pytest.mark.xdist_group("ffmpeg")]


def test_cpu_ending_fades_to_white_with_silent_audio(tmp_path: Path):
    service = RenderingService(TitleScreenConfig(use_gpu_rendering=False))
    output = tmp_path / "ending.mp4"
    service.create_title_video(
        "The end",
        None,
        TitleStyle(name="cpu"),
        output,
        width=320,
        height=180,
        duration=3.0,
        fps=10,
        animated_background=True,
        is_ending=True,
        fade_to_white=True,
    )
    first = extract_frame_rgb(output, 0, 320, 180)
    middle = extract_frame_rgb(output, 12, 320, 180)
    last = extract_frame_rgb(output, 29, 320, 180)
    assert middle.max() > 180
    assert first.mean() < 80
    assert last.mean() > 220
    stream = ffprobe_stream(output)
    assert float(stream["duration"]) == pytest.approx(3.0, abs=0.05)
    assert stream["r_frame_rate"] == "10/1"
    assert has_audio_stream(output)
    audio = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(output), "-map", "0:a", "-f", "s16le", "pipe:1"],
        capture_output=True,
        check=True,
        timeout=15,
    )
    assert np.max(np.abs(np.frombuffer(audio.stdout, dtype=np.int16))) == 0
    counted = subprocess.run(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-count_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=nb_read_frames",
            "-of",
            "json",
            str(output),
        ],
        capture_output=True,
        check=True,
        timeout=15,
    )
    assert int(json.loads(counted.stdout)["streams"][0]["nb_read_frames"]) == 30


def test_cpu_opening_keeps_content_background_and_fades_text(tmp_path: Path):
    service = RenderingService(TitleScreenConfig(use_gpu_rendering=False))
    output = tmp_path / "opening.mp4"
    background = np.full((320, 180, 3), (0.05, 0.10, 0.18), dtype=np.float32)
    service.create_title_video(
        "Summer",
        "2026",
        TitleStyle(name="cpu"),
        output,
        width=180,
        height=320,
        duration=3.5,
        fps=20,
        animated_background=True,
        fade_from_white=True,
        background_image=background,
    )
    first = extract_frame_rgb(output, 0, 180, 320)
    middle = extract_frame_rgb(output, 30, 180, 320)
    last = extract_frame_rgb(output, 69, 180, 320)
    assert first.mean() > 240
    assert middle.max() > 180
    # The background survives the text fade, including its blue palette.
    assert last[0, 0, 2] > last[0, 0, 0] * 2
    assert abs(middle[0, 0].mean() - last[0, 0].mean()) < 5
    assert middle[100:220].mean() > last[100:220].mean() + 5
    stream = ffprobe_stream(output)
    assert (stream["width"], stream["height"]) == (180, 320)
    assert stream["r_frame_rate"] == "20/1"


@pytest.mark.parametrize("transfer", ["hlg", "pq"])
def test_cpu_title_keeps_hdr_transfer_and_ten_bit_pixels(tmp_path: Path, transfer: str):
    from dataclasses import replace

    from immich_memories.processing.encoding_plan import HdrTransfer, OutputCodec
    from immich_memories.titles.cpu_video import create_title_video
    from immich_memories.titles.encoding import standalone_title_encoding_plan

    plan = replace(
        standalone_title_encoding_plan(),
        codec=OutputCodec.H265,
        encoder="libx265",
        encoder_args=("-preset", "ultrafast", "-x265-params", "log-level=error:pools=1"),
        target_transfer=HdrTransfer(transfer),
        pixel_format="yuv420p10le",
    )
    output = tmp_path / f"hdr-{transfer}.mp4"
    create_title_video(
        "Memory",
        None,
        TitleStyle(name="hdr"),
        output,
        width=320,
        height=180,
        duration=2.0,
        fps=10,
        encoding_plan=plan,
    )
    stream = ffprobe_stream(output)
    assert stream["pix_fmt"] == "yuv420p10le"
    assert stream["color_primaries"] == "bt2020"
    assert stream["color_transfer"] == ("arib-std-b67" if transfer == "hlg" else "smpte2084")
    assert extract_frame_rgb(output, 10, 320, 180).std() > 5


def test_cpu_black_fades_preserve_content_between_film_edges(tmp_path: Path):
    service = RenderingService(TitleScreenConfig(use_gpu_rendering=False, fade_color="black"))
    output = tmp_path / "black-edges.mp4"
    service.create_title_video(
        "Summer",
        None,
        TitleStyle(name="cpu"),
        output,
        width=320,
        height=180,
        duration=3.0,
        fps=10,
        animated_background=False,
        fade_from_white=True,
        fade_to_white=True,
        background_image=np.full((180, 320, 3), 0.6, dtype=np.float32),
    )
    first = extract_frame_rgb(output, 0, 320, 180)
    middle = extract_frame_rgb(output, 12, 320, 180)
    last = extract_frame_rgb(output, 29, 320, 180)
    assert first.mean() < 5
    assert middle.mean() > 100
    assert last.mean() < 15
    assert has_audio_stream(output)


def test_generator_black_ending_uses_selected_global_color(tmp_path: Path):
    from immich_memories.titles.generator import TitleScreenGenerator

    generator = TitleScreenGenerator(
        config=TitleScreenConfig(
            use_gpu_rendering=False,
            fade_color="black",
            resolution_width=320,
            resolution_height=180,
            ending_duration=3.0,
            fps=10,
        ),
        style=TitleStyle(name="ending"),
        output_dir=tmp_path,
    )
    ending = generator.generate_ending_screen()
    assert extract_frame_rgb(ending.path, 29, 320, 180).mean() < 15


def test_cpu_map_opening_uses_configured_black_fade(tmp_path: Path):
    service = RenderingService(TitleScreenConfig(use_gpu_rendering=False, fade_color="black"))
    output = tmp_path / "black-map-opening.mp4"
    service.create_map_video(
        "Summer trip",
        None,
        np.full((180, 320, 3), 0.6, dtype=np.float32),
        output,
        width=320,
        height=180,
        duration=3.0,
        fps=10,
    )
    assert extract_frame_rgb(output, 0, 320, 180).mean() < 5
    assert extract_frame_rgb(output, 12, 320, 180).max() > 100


def test_cpu_title_silence_ends_without_relying_on_the_output_limit(tmp_path, monkeypatch):
    from immich_memories.titles.cpu_video import create_title_video

    run = subprocess.run
    silence_sources = []

    def record_command(command, **kwargs):
        silence_sources.extend(arg for arg in command if str(arg).startswith("anullsrc="))
        return run(command, **kwargs)

    duration = 1.25
    with monkeypatch.context() as patch:
        # Observe the external FFmpeg boundary while still rendering a real title.
        patch.setattr(subprocess, "run", record_command)
        create_title_video(
            "Memory",
            None,
            TitleStyle(name="cpu"),
            tmp_path / "title.mp4",
            width=160,
            height=90,
            duration=duration,
            fps=24,
        )

    assert len(silence_sources) == 1
    samples = run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            silence_sources[0],
            # A guard above the requested duration keeps the broken source bounded.
            "-t",
            str(duration + 0.1),
            "-c:a",
            "pcm_s16le",
            "-f",
            "s16le",
            "pipe:1",
        ],
        capture_output=True,
        check=True,
        timeout=15,
    )
    stereo_samples = len(samples.stdout) // 4
    expected = round(duration * 48000)
    # The source may round its final packet up to its 1024-sample frame boundary.
    assert expected <= stereo_samples < expected + 1024
