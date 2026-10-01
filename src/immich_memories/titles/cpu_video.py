"""Still title plates with FFmpeg fades for machines without a rendering GPU."""

from __future__ import annotations

import logging
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np
from PIL import Image

from immich_memories.processing.encoding_plan import EncodingPlan
from immich_memories.processing.hardware_encode import apply_hardware_encode

from .backgrounds import create_background_for_style
from .encoding import standalone_title_encoding_plan, title_color_filter, title_encoder_args
from .renderer_pil import RenderSettings, TitleRenderer
from .styles import TitleStyle

logger = logging.getLogger(__name__)


def create_title_video(
    title: str,
    subtitle: str | None,
    style: TitleStyle,
    output_path: Path,
    width: int = 1920,
    height: int = 1080,
    duration: float = 3.5,
    fps: float = 60.0,
    animated_background: bool = False,
    fade_from_white: bool = False,
    background_image: np.ndarray | None = None,
    encoding_plan: EncodingPlan | None = None,
    fade_to_white: bool = False,
    frame_progress: Callable[[int, int], None] | None = None,
    fade_color: str = "white",
) -> Path:
    """Render typography once, then encode a static background with text fades.

    CPU fallback deliberately replaces per-frame bokeh, gradients and text
    transforms with opacity fades. The resolved encoding plan still owns
    codec, transfer, hardware upload, frame rate and silent audio.
    """
    started = time.perf_counter()
    plan = encoding_plan or standalone_title_encoding_plan()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    total_frames = int(duration * fps)
    if frame_progress:
        frame_progress(0, total_frames)

    if background_image is None:
        background = create_background_for_style(
            width, height, style.background_type, style.background_colors, style.background_angle
        ).convert("RGB")
        background_image = np.asarray(background, dtype=np.float32) / 255.0
    else:
        background = Image.fromarray((background_image * 255).astype(np.uint8))

    renderer = TitleRenderer(
        style,
        RenderSettings(width, height, fps, duration, False, plan.hdr),
        background_image=background_image,
    )
    # All preset transforms have settled; only opacity changes during encoding.
    plate = renderer.render_frame(title, subtitle, frame_number=int(10 * fps))

    with tempfile.TemporaryDirectory(prefix="title-plates-", dir=output_path.parent) as scratch:
        background_path = Path(scratch) / "background.png"
        plate_path = Path(scratch) / "text.png"
        background.save(background_path)
        plate.save(plate_path)
        synthesized = time.perf_counter()
        fade_in = min(0.5, duration / 3)
        fade_out = min(1.0, duration / 3)
        graph = (
            f"[0:v]fps={fps},format=rgb24[bg];"
            f"[1:v]fps={fps},format=rgba,fade=t=in:st=0:d={fade_in}:alpha=1,"
            f"fade=t=out:st={duration - fade_out}:d={fade_out}:alpha=1[text];"
            "[bg][text]overlay=format=rgb"
        )
        if fade_from_white:
            graph += f",fade=t=in:st=0:d={min(0.8, duration / 3)}:color={fade_color}"
        if fade_to_white:
            fade = min(1.5, duration)
            graph += f",fade=t=out:st={duration - fade}:d={fade}:color={fade_color}"
        graph += f",{title_color_filter(plan)}[video]"
        cmd = [
            "ffmpeg", "-y", "-filter_complex_threads", "1",
            "-loop", "1", "-framerate", "1", "-i", str(background_path),
            "-loop", "1", "-framerate", "1", "-i", str(plate_path),
            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
            "-filter_complex", graph, "-map", "[video]", "-map", "2:a",
            *title_encoder_args(plan), "-c:a", "aac", "-b:a", "128k",
            "-t", str(duration), "-r", str(fps), "-movflags", "+faststart", str(output_path),
        ]  # fmt: skip
        cmd = apply_hardware_encode(cmd, pixel_format=plan.pixel_format, video_label="video")
        result = subprocess.run(cmd, capture_output=True, timeout=max(60, duration * 30))
        if result.returncode:
            raise RuntimeError(
                f"CPU title encode failed: {result.stderr.decode(errors='replace')[-2000:]}"
            )
    finished = time.perf_counter()
    logger.info(
        "CPU title plates: synthesis %.2fs; encode %.2fs; %dx%d, %g fps, %.2fs",
        synthesized - started,
        finished - synthesized,
        width,
        height,
        fps,
        duration,
    )
    if frame_progress:
        frame_progress(total_frames, total_frames)
    return output_path
