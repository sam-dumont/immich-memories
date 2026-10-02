"""Measure the pixels reaching the real background blur, not just its output."""

import re
import subprocess

import numpy as np
import pytest

from immich_memories.processing.streaming_frame_decoder import FrameDecoder
from tests.integration.conftest import requires_ffmpeg

pytestmark = [pytest.mark.integration, requires_ffmpeg]


@pytest.mark.parametrize(
    ("width", "height", "background"),
    [
        (2160, 3840, "540x960"),
        (1920, 1080, "960x540"),
        (720, 1280, "720x1280"),
        (1082, 1920, "1082x1920"),
    ],
)
def test_background_blur_work_matches_the_canvas_budget(tmp_path, width, height, background):
    decoder = FrameDecoder(
        tmp_path / "source.mkv",
        width,
        height,
        30,
        source_size=(720, 1280) if width > height else (1280, 720),
        scale_mode="blur",
    )
    graph = decoder._build_vf().replace(",gblur=", ",showinfo@background,gblur=", 1)
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-filter_complex_threads",
            "2",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size={'720x1280' if width > height else '1280x720'}:rate=30:duration=0.04",
            "-filter_complex",
            graph,
            "-frames:v",
            "1",
            "-an",
            "-f",
            "framemd5",
            "pipe:1",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    sizes = re.findall(r"showinfo@background[^\n]* s:(\d+x\d+)", result.stderr)
    assert sizes and set(sizes) == {background}
    assert f"#dimensions 0: {width}x{height}" in result.stdout
    assert len([line for line in result.stdout.splitlines() if line.startswith("0,")]) == 1


@pytest.mark.parametrize("transfer", ["bt709", "smpte2084", "arib-std-b67"])
def test_reduced_background_keeps_sharp_pixels_and_high_similarity(tmp_path, transfer):
    width, height = 1080, 1920
    decoder = FrameDecoder(
        tmp_path / "source.mkv",
        width,
        height,
        30,
        pix_fmt="yuv420p10le",
        source_size=(1280, 720),
        scale_mode="blur",
    )
    graph = decoder._build_vf()
    # Independent reference: the previous full-canvas background, including its
    # original crop behavior. The foreground and overlay remain the same.
    full = (
        f"[_bg]scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={width}:{height},gblur=sigma=30[_blurred]"
    )
    reference = re.sub(r"\[_bg\]scale=.*?\[_blurred\]", lambda _: full, graph)
    frames = []
    for chain in (reference, graph):
        result = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-filter_complex_threads",
                "2",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=1280x720:rate=30:duration=0.04,format=yuv420p10le,"
                f"setparams=color_primaries=bt2020:colorspace=bt2020nc:color_trc={transfer}",
                "-filter_complex",
                chain,
                "-frames:v",
                "1",
                "-an",
                "-pix_fmt",
                "yuv420p10le",
                "-f",
                "rawvideo",
                "pipe:1",
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        assert len(result.stdout) == width * height * 3
        frames.append(np.frombuffer(result.stdout, dtype="<u2").astype(np.int32))
    delta = np.abs(frames[0] - frames[1])
    # The source fits to 1080x608. Leave the chroma interpolation boundary out;
    # these interior luma/chroma pixels must remain completely unchanged.
    luma = delta[: width * height].reshape(height, width)
    chroma = delta[width * height :].reshape(2, height // 2, width // 2)
    assert not luma[664:1256, 8:-8].any()
    assert not chroma[:, 332:628, 4:-4].any()
    mse = np.mean(delta.astype(np.float64) ** 2)
    assert 10 * np.log10(1023**2 / mse) > 50
