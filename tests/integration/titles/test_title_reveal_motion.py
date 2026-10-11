"""A title that opens on a moving video reveals it in smooth slow motion.

The deblur ends on the first clip, so the last stretch of the title is the clip
coming into focus in slow motion. A camera pan seen there has to advance on
every frame along the slow-motion curve and reach the clip's own speed at the
cut. Cross-fading slowed-down source frames can't do that: two frames twelve
pixels apart blended together are a double exposure, not a picture halfway
between them, so the pan held for two frames and jumped a whole frame on the
third, then sped up at the cut (#2389).

Each test renders a whole film through the assembler, opening on a clip that
pans across a random texture at a known speed, and finds every frame's place on
that texture. The title plays the clip's first half-second, so source frame s
sits at s times the pan speed.

Run: make test-integration-titles
"""

from __future__ import annotations

import math
import os
import subprocess
from pathlib import Path

import cv2
import numpy as np
import pytest

os.environ["IMMICH_FORCE_CPU"] = "1"

from immich_memories.processing.assembly_config import (  # noqa: E402
    AssemblyClip,
    AssemblySettings,
    TitleScreenSettings,
    TransitionType,
    standalone_assembly_encoding_plan,
)
from immich_memories.processing.video_assembler import VideoAssembler  # noqa: E402
from immich_memories.titles.kernels import KERNELS_AVAILABLE  # noqa: E402
from tests.integration.conftest import requires_ffmpeg  # noqa: E402

pytestmark = [
    pytest.mark.integration,
    requires_ffmpeg,
    pytest.mark.skipif(not KERNELS_AVAILABLE, reason="no kernel library wheel for this platform"),
]

WIDTH, HEIGHT = 320, 180
PAN_PX_PER_FRAME = 8
CLIP_SECONDS = 3.0
TITLE_SECONDS = 3.5
BORROWED_SECONDS = 0.5
# How far a frame may sit from where the slow-motion curve puts it.
PLACE_TOLERANCE = 0.25 * PAN_PX_PER_FRAME
# Rows below the title text, where only the background shows.
BAND = slice(int(HEIGHT * 0.72), int(HEIGHT * 0.95))


def _texture(path: Path, width: int) -> np.ndarray:
    """A smooth random texture with no repeating pattern to mismatch against."""
    rng = np.random.default_rng(2389)
    noise = rng.uniform(0, 255, (HEIGHT, width, 3)).astype(np.float32)
    texture = cv2.GaussianBlur(noise, (0, 0), 3)
    texture = cv2.normalize(texture, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    cv2.imwrite(str(path), texture)
    return cv2.cvtColor(texture, cv2.COLOR_BGR2GRAY).astype(np.float32)


def _panning_clip(texture: Path, out: Path, fps: int, seconds: float) -> None:
    subprocess.run(  # noqa: S603, S607 — fixed argv, no shell
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-loop",
            "1",
            "-framerate",
            str(fps),
            "-i",
            str(texture),
            "-t",
            str(seconds),
            "-vf",
            f"crop={WIDTH}:{HEIGHT}:x='n*{PAN_PX_PER_FRAME}':y=0,format=yuv420p",
            "-c:v",
            "libx264",
            "-qp",
            "0",
            str(out),
        ],  # fmt: skip
        check=True,
        timeout=60,
    )


def _render_film(clip: Path, out: Path, seconds: float) -> Path:
    settings = AssemblySettings(
        encoding_plan=standalone_assembly_encoding_plan(16),
        transition=TransitionType.CUT,
        auto_resolution=False,
        target_resolution=(WIDTH, HEIGHT),
        normalize_clip_audio=False,
        title_screens=TitleScreenSettings(
            year=2024,
            title_duration=TITLE_SECONDS,
            show_ending_screen=False,
            show_month_dividers=False,
        ),
    )
    film = out / "film.mp4"
    VideoAssembler(settings).assemble_with_titles([AssemblyClip(path=clip, duration=seconds)], film)
    return film


def _gray_frames(film: Path, *filters: str) -> np.ndarray:
    vf = ["-vf", ",".join(filters)] if filters else []
    raw = subprocess.run(  # noqa: S603, S607 — fixed argv, no shell
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(film),
            *vf,
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "pipe:1",
        ],
        capture_output=True,
        check=True,
        timeout=60,
    ).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, HEIGHT, WIDTH)


def _place_on_texture(frame: np.ndarray, texture: np.ndarray) -> float:
    """Where on the texture this frame's background band sits, to a tenth of a pixel."""
    margin = 16
    patch = frame[BAND, margin:-margin].astype(np.float32)
    scores = cv2.matchTemplate(texture[BAND], patch, cv2.TM_CCOEFF_NORMED)[0]
    best = int(np.argmax(scores))
    offset = 0.0
    if 0 < best < len(scores) - 1:
        left, mid, right = scores[best - 1], scores[best], scores[best + 1]
        curve = left - 2 * mid + right
        offset = 0.5 * (left - right) / curve if curve else 0.0
    return best + offset - margin


def _render_pan(fps: int, out: Path, seconds: float) -> tuple[np.ndarray, np.ndarray, Path]:
    """Every frame of a film opening on a pan, the texture it pans across, and the clip."""
    texture_path = out / "texture.png"
    texture = _texture(texture_path, WIDTH + int(seconds * fps) * PAN_PX_PER_FRAME + 64)
    clip = out / "pan.mp4"
    _panning_clip(texture_path, clip, fps, seconds)
    return _gray_frames(_render_film(clip, out, seconds)), texture, clip


def _pan_film(fps: int, out: Path, seconds: float = CLIP_SECONDS) -> tuple[list[float], int]:
    """Each frame's place on the texture, for a film opening on a pan, and the cut frame."""
    frames, texture, _ = _render_pan(fps, out, seconds)
    cut = int(TITLE_SECONDS * fps)  # first frame of the clip itself
    return [_place_on_texture(frames[n], texture) for n in range(cut + fps // 2)], cut


def _slow_motion_place(frame: int, fps: int) -> float:
    """Where the slow-motion curve puts a title frame: 1x on the last source frame."""
    sources = math.ceil(BORROWED_SECONDS * fps)
    last = int(TITLE_SECONDS * fps) - 1
    exponent = last / (sources - 1)
    return (sources - 1) * (frame / last) ** exponent * PAN_PX_PER_FRAME


def _title_renderer(monkeypatch: pytest.MonkeyPatch, *, kernels: bool) -> None:
    """Pin which renderer draws the title, the same on a Mac, Linux CI or a NAS.

    WHY: the renderer follows the GPU probe, so a Mac always took the kernel
    path and Linux CI never did. Kernels: the probe reports a backend and the
    CPU kernel backend counts as one; it runs the same kernels Metal, CUDA and
    Vulkan do. Otherwise: no GPU, so the FFmpeg still-title path most NAS run.
    """
    probe = "immich_memories.titles.kernel_backend_probe.gpu_backend"
    if not kernels:
        monkeypatch.setattr(probe, lambda _system: (None, ("no GPU in this test",)))
        return
    monkeypatch.setattr(probe, lambda _system: ("CPU", ()))
    monkeypatch.setattr(
        "immich_memories.titles.rendering_service._GPU_BACKENDS",
        frozenset({"Metal", "CUDA", "Vulkan", "CPU"}),
    )


@pytest.mark.parametrize("fps", [24, 25, 30, 60])
def test_the_reveal_slows_smoothly_and_reaches_clip_speed_at_the_cut(
    fps: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _title_renderer(monkeypatch, kernels=True)
    places, cut = _pan_film(fps, tmp_path)

    # The last half-second of the deblur, when the picture is mostly in focus.
    sharpening = range(cut - fps // 2, cut)
    astray = [
        (n, round(places[n] - _slow_motion_place(n, fps), 2))
        for n in sharpening
        if abs(places[n] - _slow_motion_place(n, fps)) > PLACE_TOLERANCE
    ]
    stalls = [n for n in sharpening[1:] if places[n] - places[n - 1] < 0.1 * PAN_PX_PER_FRAME]
    at_the_cut = places[cut] - places[cut - 1]

    assert not astray, f"at {fps} fps these title frames left the slow-motion curve: {astray}"
    assert not stalls, f"at {fps} fps the background stood still on frames {stalls}"
    assert abs(at_the_cut - PAN_PX_PER_FRAME) <= 0.25 * PAN_PX_PER_FRAME, (
        f"at {fps} fps the cut stepped {at_the_cut:.2f} px; the clip pans {PAN_PX_PER_FRAME}"
    )
    assert np.allclose(np.diff(places[cut:]), PAN_PX_PER_FRAME, atol=0.5)


def test_without_interpolation_the_reveal_plays_at_clip_speed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Over its budget the opening plays its source frame for frame, never blended."""
    _title_renderer(monkeypatch, kernels=True)
    # WHY: the time budget is the fallback's trigger; zero forces it here.
    monkeypatch.setattr("immich_memories.titles.motion_interpolation.BUDGET_SECONDS", 0.0)
    fps = 30
    places, cut = _pan_film(fps, tmp_path)

    sources = math.ceil(BORROWED_SECONDS * fps)
    steps = [places[n] - places[n - 1] for n in range(cut - (sources - 2), cut + fps // 2)]

    assert np.allclose(steps, PAN_PX_PER_FRAME, atol=0.25 * PAN_PX_PER_FRAME), steps


def _still_shows(title_frame: np.ndarray, clip: Path) -> int:
    """Which frame of the clip a still title shows.

    The still is blurred too hard to place on the sharp texture (that read
    differently on Linux and macOS), so compare it with every clip frame
    blurred the way the still is; normalised correlation ignores its dimming.
    """
    blurred = _gray_frames(clip, "gblur=sigma=30")
    still = title_frame[BAND].astype(np.float32)
    scores = [
        float(cv2.matchTemplate(frame[BAND].astype(np.float32), still, cv2.TM_CCOEFF_NORMED)[0, 0])
        for frame in blurred
    ]
    return int(np.argmax(scores))


@pytest.mark.parametrize(
    ("fps", "clip_seconds"), [(25, CLIP_SECONDS), (60, CLIP_SECONDS), (25, 1.4)]
)
def test_a_still_title_shows_the_frame_before_the_clip_resumes(
    fps: int, clip_seconds: float, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a GPU the title holds a blurred still, and the clip carries on from it.

    A clip that can spare half a second lends it to the title and resumes after
    it, so the still is the last lent frame. One too short (1.4 s) lends
    nothing and starts on its first frame, so the still is that frame.
    """
    _title_renderer(monkeypatch, kernels=False)
    frames, texture, clip = _render_pan(fps, tmp_path, clip_seconds)
    cut = int(TITLE_SECONDS * fps)
    lent = math.ceil(BORROWED_SECONDS * fps) if clip_seconds > BORROWED_SECONDS + 1.0 else 0

    resumes_at = _place_on_texture(frames[cut], texture) / PAN_PX_PER_FRAME
    shows = _still_shows(frames[cut - 1], clip)

    assert abs(resumes_at - lent) < 0.25, f"the clip resumed at frame {resumes_at:.2f}"
    # Neighbouring frames differ by 8 px under a 30 px blur, so one either way
    # is as close as the still can be told apart; a skip or replay is 12 or more.
    assert abs(shows - max(lent - 1, 0)) <= 1, (
        f"the still shows clip frame {shows}; the clip resumes at frame {lent}"
    )
