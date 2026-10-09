"""Decoding one clip into normalized frames for the streaming assembler.

Kept apart from the assembler because this is the source half of the pipe: it
owns the per-clip FFmpeg filter chain (rotation, privacy blur, fit/blur fill,
HDR transfer, captions) and hands back raw frames plus the clip's audio. The
assembler only consumes the frames.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Generator, Iterator
from fractions import Fraction
from io import BufferedReader
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event, Thread
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import numpy as np

from immich_memories.processing.clip_caption import ClipCaption, caption_filters
from immich_memories.processing.ffmpeg_runner import stop_owned_process
from immich_memories.processing.hdr_utilities import (
    _detect_color_primaries,
    _detect_hdr_type,
    _resolve_clip_hdr,
    get_colorspace_filter,
)
from immich_memories.processing.memory_budget import assembly_decoder_threads, available_cpus
from immich_memories.processing.probe_cache import ProbeCache

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from immich_memories.processing.probe_cache import VideoProbe


class FrameDecoder:
    """Decode a video clip to raw frames via FFmpeg stdout pipe."""

    def __init__(
        self,
        clip_path: Path,
        width: int,
        height: int,
        fps: int,
        pix_fmt: str = "rgb24",
        rotation: int = 0,
        privacy_blur: bool = False,
        hdr_conversion: str = "",
        colorspace_filter: str = "",
        output_pix_fmt: str = "",
        scale_mode: str = "black",
        sdr_to_hdr_filter: str = "",
        input_seek: float = 0.0,
        audio_output: Path | None = None,
        caption: ClipCaption | None = None,
        caption_font: str | None = None,
        caption_window: tuple[int, int] | None = None,
        source_size: tuple[int, int] | None = None,
        threads: int | None = None,
        source_frame_rate: Fraction | None = None,
        frame_limit: int | None = None,
        probe_cache: ProbeCache | None = None,
    ) -> None:
        self._clip_path = clip_path
        self._probe_cache = probe_cache or ProbeCache()
        self._source_size = source_size
        self._threads = threads
        self._source_frame_rate = source_frame_rate
        self._input_seek = input_seek
        self._audio_output = audio_output
        self._frame_limit = frame_limit
        self._width = width
        self._height = height
        self._fps = fps
        self._pix_fmt = pix_fmt
        self._frame_size = width * height * 3  # Same for yuv420p10le and rgb24
        self._rotation = rotation
        self._privacy_blur = privacy_blur
        self._hdr_conversion = hdr_conversion
        self._colorspace_filter = colorspace_filter
        self._output_pix_fmt = output_pix_fmt
        self._scale_mode = scale_mode
        # WHY: SDR clips in HDR output need zscale to convert sRGB→HLG/PQ.
        # Without this, SDR full-range data piped as yuv420p10le gets
        # interpreted as TV-range HLG = red/wrong tint.
        self._sdr_to_hdr_filter = sdr_to_hdr_filter
        self._caption = caption
        self._caption_font = caption_font
        self._caption_window = caption_window

    def _covers_canvas(self) -> bool:
        if self._source_size is None:
            return False
        width, height = self._source_size
        if self._rotation in (90, 270):
            width, height = height, width
        return width * self._height == height * self._width

    def _blur_background(self) -> str:
        # Only the soft background is reduced. Even chroma dimensions and exact
        # cropping keep its center aligned with the full-resolution foreground.
        factor = 4 if min(self._width, self._height) >= 2160 else 2
        if (
            self._privacy_blur
            or min(self._width, self._height) < 1080
            or self._width % (2 * factor)
            or self._height % (2 * factor)
        ):
            factor = 1
        width, height = self._width // factor, self._height // factor
        crop = ":exact=1" if factor > 1 else ""
        chain = (
            f"[_bg]scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={width}:{height}{crop}"
        )
        if not self._privacy_blur:
            chain += f",gblur=sigma={30 / factor:g}"
        if factor > 1:
            chain += f",scale={self._width}:{self._height}:flags=bilinear"
        return chain + "[_blurred]"

    def _fill_filters(self) -> list[str]:
        """Scale to the canvas and fill what the source leaves uncovered."""
        if self._covers_canvas():
            # WHY (#1527): a source with the canvas's exact shape scales to fill it,
            # so a blur fill would sit entirely under it: at 4K that background cost
            # about 5 s of CPU and 130 MB per clip for pixels nobody sees.
            self._use_filter_complex = False
            return [f"scale={self._width}:{self._height}:flags=lanczos"]
        if self._scale_mode == "blur":
            # WHY: Blur background fills the entire frame with a blurred, zoomed version
            # of the source, then overlays the sharp scaled version centered on top.
            # Uses split to avoid re-reading the source.
            # When privacy blur is active, skip the extra sigma=30 on the background
            # because the frame is already blurred — adding more makes it unrecognizable.
            # WHY (#1527): overlay composites in 8-bit yuv420 unless told otherwise,
            # which rounded every HDR frame with a blur fill to multiples of 4.
            overlay_format = ":format=yuv420p10" if self._pix_fmt != "rgb24" else ""
            self._use_filter_complex = True
            return [
                "split[_bg][_fg]",
                self._blur_background(),
                f"[_fg]scale={self._width}:{self._height}:force_original_aspect_ratio=decrease:flags=lanczos[_sharp]",
                f"[_blurred][_sharp]overlay=(W-w)/2:(H-h)/2{overlay_format}",
            ]
        # "fit": scale down inside the frame and pad the rest black. There is
        # no face-aware crop on the video path, so anything that is not
        # "blur" lands here — which is why no such mode is offered.
        self._use_filter_complex = False
        return [
            f"scale={self._width}:{self._height}:force_original_aspect_ratio=decrease:flags=lanczos",
            f"pad={self._width}:{self._height}:(ow-iw)/2:(oh-ih)/2:black",
        ]

    def _build_vf(self) -> str:
        """Build the -vf filter chain applied to every decoded clip."""
        parts: list[str] = []

        # Rotation (transpose/hflip) — must come before scale
        if self._rotation == 90:
            parts.append("transpose=1")
        elif self._rotation == 180:
            parts.append("hflip,vflip")
        elif self._rotation == 270:
            parts.append("transpose=2")

        # WHY: frosted glass effect — gaussian blur + noise texture + smooth.
        # Looks cinematic/artistic rather than surveillance-like pixelation.
        # Scales with shorter dimension so portrait/landscape match.
        if self._privacy_blur:
            short_side = min(self._width, self._height)
            sigma = int(short_side * 0.035)
            parts.append(f"gblur=sigma={sigma},noise=alls=15:allf=t,gblur=sigma=10")

        # PTS reset — critical for multi-clip concat
        parts.append("setpts=PTS-STARTPTS")

        # Normalize equal rates before overlay: FFmpeg 6 can lose the final
        # frame duration there, so a later fps filter drops that frame. Higher
        # rates also skip discarded spatial work. Preserve privacy-noise order.
        early_fps = (
            not self._privacy_blur
            and self._source_frame_rate is not None
            and self._source_frame_rate >= self._fps
        )
        if early_fps:
            parts.append(f"fps={self._fps},settb=1/{self._fps}")

        # Scale + fill to target resolution
        parts.extend(self._fill_filters())

        # A frame-local transfer need only run once per source frame. Duplication
        # before it made a 30 → 60 fps HDR conversion do the same work twice.
        # Keep the original order for privacy noise and unknown/ambiguous cadence.
        # Captions still see the final frame grid.
        defer_fps = (
            self._pix_fmt == "yuv420p10le"
            and not self._privacy_blur
            and self._source_frame_rate is not None
            and 0 < self._source_frame_rate < self._fps
            and bool(self._hdr_conversion or self._sdr_to_hdr_filter)
        )
        if not (defer_fps or early_fps):
            parts.append(f"fps={self._fps},settb=1/{self._fps}")

        # SDR→HDR conversion (only for SDR clips in HDR output)
        if self._sdr_to_hdr_filter:
            parts.append(self._sdr_to_hdr_filter)

        # Apply the shared per-source transfer conversion and tag the decoded
        # frames before they enter the metadata-free rawvideo pipe.
        for color_filter in (
            self._hdr_conversion,
            self._colorspace_filter,
            self._output_pix_fmt,
        ):
            if color_filter:
                parts.append(color_filter.removeprefix(","))

        if defer_fps:
            parts.append(f"fps={self._fps},settb=1/{self._fps}")

        # Drawn last so the text is never scaled, padded or blurred with the
        # source, and lands in target-frame coordinates.
        if self._caption:
            parts.extend(
                caption_filters(
                    self._caption,
                    self._width,
                    self._height,
                    is_hdr=self._pix_fmt != "rgb24",
                    font_path=self._caption_font,
                    frame_window=self._caption_window,
                )
            )

        # Square pixels
        parts.append("setsar=1")

        return ",".join(parts)

    def __iter__(self) -> Iterator[np.ndarray]:
        """Yield independent, read-only frames that callers may retain."""
        return self._iter_frames(reuse_buffer=False)

    def iter_borrowed_frames(
        self, *, read_ahead: bool = False
    ) -> Generator[np.ndarray, None, None]:
        """Yield read-only views valid until the next complete frame arrives.

        Exhaustion preserves the last frame for crossfade holds. Copy frames
        before advancing if they must remain available beyond the next yield.
        Read-ahead uses three slots; the synchronous path uses two.
        """
        return self._iter_frames(reuse_buffer=True, read_ahead=read_ahead)

    def _iter_frames(
        self, reuse_buffer: bool, read_ahead: bool = False
    ) -> Generator[np.ndarray, None, None]:
        vf = self._build_vf()
        use_fc = getattr(self, "_use_filter_complex", False)

        if use_fc:
            # WHY: Blur background uses split which requires -filter_complex
            filter_args = ["-filter_complex", f"[0:v]{vf}[out]", "-map", "[out]"]
        else:
            filter_args = ["-vf", vf]

        seek_args = ["-ss", str(self._input_seek)] if self._input_seek > 0 else []

        # WHY: Extract audio alongside video in the same FFmpeg pass.
        # Audio timing matches the decoded video frames exactly, preventing
        # the cumulative drift from independent video/audio assembly.
        audio_inputs, audio_map = self._audio_input()
        audio_args = self._audio_output_args(audio_map)

        video_limit = ["-frames:v", str(self._frame_limit)] if self._frame_limit is not None else []

        threads = self._threads if self._threads is not None else assembly_decoder_threads()
        filter_threads = str(available_cpus())
        cmd = [
            "ffmpeg",
            "-filter_threads",
            filter_threads,
            "-filter_complex_threads",
            filter_threads,
            "-threads",
            str(threads),
            *seek_args,
            "-i",
            str(self._clip_path),
            *audio_inputs,
            "-f",
            "rawvideo",
            "-pix_fmt",
            self._pix_fmt,
            *filter_args,
            "-s",
            f"{self._width}x{self._height}",
            "-r",
            str(self._fps),
            *video_limit,
            "pipe:1",
            *audio_args,
        ]
        logger.debug(f"FrameDecoder cmd: {' '.join(cmd)}")
        proc = subprocess.Popen(  # noqa: S603, S607
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=self._frame_size,
        )
        assert proc.stdout is not None  # noqa: S101
        # Popen's positive bufsize gives this binary pipe a BufferedReader.
        pipe = cast(BufferedReader, proc.stdout)

        raw_frames = (
            _FrameReadAhead(pipe, self._frame_size).frames()
            if read_ahead
            else self._raw_frames(pipe, reuse_buffer)
        )
        try:
            for decoded, raw in enumerate(raw_frames, start=1):
                frame: np.ndarray
                if self._pix_fmt == "yuv420p10le":
                    # WHY: Keep as flat uint16 — YUV planar can't reshape to (H,W,3).
                    # Crossfade blends each sample independently which works for all planes.
                    # The array retains `raw`; body writes, previews and crossfades
                    # only read it. Keep the same bytes-backed view as SDR rather
                    # than copying another 25 MB for every 4K HDR frame.
                    frame = np.frombuffer(raw, dtype=np.uint16)
                else:
                    frame = np.frombuffer(raw, dtype=np.uint8).reshape(self._height, self._width, 3)
                frame.setflags(write=False)
                self._finish_bounded_output(proc, decoded)
                yield frame
        finally:
            # Stop the writer before joining a reader blocked on its pipe.
            stop_owned_process(proc)
            try:
                raw_frames.close()
            finally:
                proc.stdout.close()

    def _raw_frames(
        self, pipe: BufferedReader, reuse_buffer: bool
    ) -> Generator[bytes | bytearray, None, None]:
        # Read into the other slot: an incomplete write must not overwrite
        # the last complete frame, which a crossfade may need to hold.
        storage = [bytearray(self._frame_size) for _ in range(2)] if reuse_buffer else None
        index = 0
        raw: bytes | bytearray
        while True:
            if storage is None:
                raw = pipe.read(self._frame_size)
                size = len(raw)
            else:
                raw = storage[index % 2]
                size = pipe.readinto(raw)
            if size != self._frame_size:
                return
            yield raw
            index += 1

    def _finish_bounded_output(self, proc: subprocess.Popen[bytes], decoded: int) -> None:
        # The assembler closes this generator after its last picture.
        # Both outputs are bounded, so let the WAV finish before that
        # close can SIGTERM a still-writing audio producer.
        if (
            self._frame_limit is not None
            and decoded == self._frame_limit
            and proc.wait(timeout=10) != 0
        ):
            raise RuntimeError("Frame decoder failed before completing clip audio")

    def _audio_output_args(self, audio_map: str) -> list[str]:
        if not self._audio_output:
            return []
        duration = (
            ["-t", str(self._frame_limit / self._fps)] if self._frame_limit is not None else []
        )
        return [
            "-map",
            audio_map,
            "-c:a",
            "pcm_s16le",
            "-ar",
            "48000",
            "-ac",
            "2",
            *duration,
            str(self._audio_output),
        ]

    def _audio_input(self) -> tuple[list[str], str]:
        if self._audio_output is None:
            return [], "0:a?"
        probe = self._probe_cache.get(self._clip_path)
        if probe.has_audio:
            return [], "0:a?"
        # Optional mapping still fails when the WAV has no stream. Supply silence
        # for exactly the remaining source time, so video decoding can proceed.
        duration = max(0.0, probe.duration_seconds - self._input_seek)
        return ["-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo:d={duration}"], "1:a:0"


def make_decoder(
    clip: Any,
    clip_idx: int,
    width: int,
    height: int,
    fps: int,
    ctx: Any | None = None,
    privacy_mode: bool = False,
    caption: ClipCaption | None = None,
    caption_font: str | None = None,
    scale_mode: str = "black",
    hdr_type: str | None = None,
    audio_work_dir: Path | None = None,
    caption_window: tuple[int, int] | None = None,
    probe_cache: ProbeCache | None = None,
) -> FrameDecoder:
    """Create a FrameDecoder with per-clip normalization filters."""
    probe_cache = probe_cache or ProbeCache()
    rotation = 0
    is_title = getattr(clip, "is_title_screen", False)

    rotation_override = getattr(clip, "rotation_override", None)
    if rotation_override is not None and rotation_override != 0:
        rotation = rotation_override

    if ctx is None and Path(clip.path).exists():
        target_type = hdr_type or "sdr"
        source_types: list[str | None] = [None] * (clip_idx + 1)
        source_primaries: list[str | None] = [None] * (clip_idx + 1)
        source_types[clip_idx] = _detect_hdr_type(clip.path, probe_cache=probe_cache)
        source_primaries[clip_idx] = _detect_color_primaries(clip.path, probe_cache=probe_cache)
        ctx = SimpleNamespace(
            hdr_type=target_type,
            pix_fmt="yuv420p10le" if hdr_type else "yuv420p",
            clip_hdr_types=source_types,
            clip_primaries=source_primaries,
            colorspace_filter=get_colorspace_filter(target_type),
        )

    # Title videos may be pre-encoded, but only an exact transfer match may
    # bypass conversion. The shared resolver makes the same decision for all clips.
    hdr_conversion, colorspace_filter, output_pix_fmt, sdr_to_hdr_filter, _ = _resolve_clip_hdr(
        clip_idx, ctx, hdr_type
    )
    pix_fmt = "yuv420p10le" if hdr_type else "rgb24"
    logger.info(
        f"Decoder[{clip_idx}] pix={pix_fmt} title={is_title} hdr_type={hdr_type} "
        f"sdr2hdr={bool(sdr_to_hdr_filter)} {clip.path.name}"
    )

    audio_output = None
    if audio_work_dir:
        audio_output = audio_work_dir / f"clip_{clip_idx}_audio.wav"

    source_size, source_frame_rate = _source_properties(clip.path, probe_cache)
    return FrameDecoder(
        clip_path=clip.path,
        probe_cache=probe_cache,
        width=width,
        height=height,
        fps=fps,
        pix_fmt=pix_fmt,
        rotation=rotation,
        privacy_blur=privacy_mode and not is_title,
        hdr_conversion=hdr_conversion,
        colorspace_filter=colorspace_filter,
        output_pix_fmt=output_pix_fmt,
        scale_mode=scale_mode,
        sdr_to_hdr_filter=sdr_to_hdr_filter,
        input_seek=getattr(clip, "input_seek", 0.0),
        audio_output=audio_output,
        caption=caption if not is_title else None,
        caption_font=caption_font,
        caption_window=caption_window,
        source_size=source_size,
        source_frame_rate=source_frame_rate,
        frame_limit=int(clip.duration * fps) if audio_work_dir is not None else None,
    )


def _source_properties(
    path: Path, probe_cache: ProbeCache | None = None
) -> tuple[tuple[int, int] | None, Fraction | None]:
    """Read geometry and cadence from one probe, retaining the unprobed fallback."""
    from immich_memories.processing.probe_cache import ProbeError

    try:
        probe = (probe_cache or ProbeCache()).get(path)
    except (ProbeError, OSError, ValueError):
        return None, None
    return probe.resolution, _matching_stream_rate(probe)


def _matching_stream_rate(probe: VideoProbe) -> Fraction | None:
    """Use the existing matching-stream-rates fast path; ambiguity keeps the graph."""
    try:
        average = Fraction(probe.average_frame_rate or "0")
        nominal = Fraction(probe.nominal_frame_rate or "0")
    except (ValueError, ZeroDivisionError):
        return None
    return average if average > 0 and average == nominal else None


class _FrameReadAhead:
    """Three slots: one held by the consumer, one queued, one being filled."""

    def __init__(self, pipe: BufferedReader, frame_size: int) -> None:
        self._pipe = pipe
        self._frame_size = frame_size
        self._available: Queue[bytearray] = Queue()
        self._pending: Queue[bytearray | BaseException | None] = Queue(maxsize=1)
        self._stopped = Event()

    def _offer(self, item: bytearray | BaseException | None) -> None:
        while not self._stopped.is_set():
            try:
                self._pending.put(item, timeout=0.1)
                return
            except Full:
                continue

    def _produce(self) -> None:
        try:
            while not self._stopped.is_set():
                try:
                    slot = self._available.get(timeout=0.1)
                except Empty:
                    continue
                if self._pipe.readinto(slot) != self._frame_size:
                    break
                self._offer(slot)
        except BaseException as exc:
            # Report worker failures on the consuming thread instead of hanging it.
            self._offer(exc)
        finally:
            self._offer(None)

    def frames(self) -> Generator[bytearray, None, None]:
        """Borrow complete frames; the owner must stop its writer before closing."""
        for _ in range(3):
            self._available.put(bytearray(self._frame_size))
        worker = Thread(target=self._produce, name="frame-read-ahead", daemon=True)
        worker.start()
        previous = None
        try:
            while True:
                item = self._pending.get()
                if item is None:
                    return
                if isinstance(item, BaseException):
                    raise item
                # A short final read must never overwrite the last complete frame.
                # Release its slot only when another complete frame replaces it.
                if previous is not None:
                    self._available.put(previous)
                previous = item
                yield item
        finally:
            self._stopped.set()
            worker.join(timeout=5)
            if worker.is_alive():
                raise RuntimeError("Frame reader did not stop after its decoder exited")
