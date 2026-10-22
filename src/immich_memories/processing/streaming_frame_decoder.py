"""Decoding one clip into normalized frames for the streaming assembler.

Kept apart from the assembler because this is the source half of the pipe: it
owns the per-clip FFmpeg filter chain (rotation, privacy blur, fit/blur fill,
HDR transfer, captions) and hands back raw frames plus the clip's audio. The
assembler only consumes the frames.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from collections.abc import Generator, Iterator
from fractions import Fraction
from io import BufferedReader
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event, Thread
from types import SimpleNamespace
from typing import IO, TYPE_CHECKING, Any, cast

import numpy as np

from immich_memories.processing.caption_image import drawtext_available
from immich_memories.processing.clip_caption import ClipCaption, caption_filters
from immich_memories.processing.ffmpeg_runner import stop_owned_process
from immich_memories.processing.gpu_frame_graph import (
    gpu_frame_graph_for_path,
    hardware_decode_for,
)
from immich_memories.processing.gpu_transfer import transfer_conversion
from immich_memories.processing.hdr_utilities import (
    detect_color_primaries,
    detect_hdr_type,
    get_colorspace_filter,
    resolve_clip_hdr,
)
from immich_memories.processing.memory_budget import assembly_decoder_threads, available_cpus
from immich_memories.processing.probe_cache import ProbeCache
from immich_memories.processing.render_control import owned_child

logger = logging.getLogger(__name__)

# After its last picture FFmpeg has nothing left to write to the pipe (-frames:v caps it,
# stdin is null, stderr and the audio go to files), so nothing the reader does can
# block it: this wait only absorbs a machine that stalls. A CI runner once paused every
# process for 14 s, past the 10 s this used to allow (#2515).
AUDIO_FINISH_SECONDS = 120.0

if TYPE_CHECKING:
    from immich_memories.processing.gpu_frame_graph import GpuFrameGraph
    from immich_memories.processing.probe_cache import VideoProbe

# 10-bit pipes: planar for libx265 and the CPU filters, P010 for hardware encoders.
_TEN_BIT_PIPES = frozenset({"yuv420p10le", "p010le"})

# FFmpeg's lines about a clip that ends short, at most this many, for the film's log.
_STDERR_LINES = 4
# FFmpeg exits right after its last write; one that lingers is read as far as it got
# and left to the cleanup, which kills it (#883).
_STDERR_WAIT_SECONDS = 5.0
# Warnings FFmpeg repeats for every clip, which say nothing about why one came out short.
_STDERR_NOISE = ("deprecated pixel format used", "Last message repeated")


class HardwareDecodeFailed(RuntimeError):
    """A clip's hardware decode failed; decoding it in software may still succeed."""


class ClipGaveNoFrames(RuntimeError):
    """The clip at ``index`` of the sequence decoded to no frame; ``why`` is FFmpeg's word.

    Holding the frame before it for the clip's whole length would freeze the
    film, so the sequence is assembled again without it (#2824).
    """

    def __init__(self, index: int, why: str | None) -> None:
        self.index = index
        self.why = why or "FFmpeg said nothing"
        super().__init__(f"Clip {index} decoded to no frame: {self.why}")


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
        hardware_decode: tuple[tuple[str, ...], str] | None = None,
        from_seconds: float = 0.0,
        gpu_graph: GpuFrameGraph | None = None,
    ) -> None:
        self._clip_path = clip_path
        # Decoded, scaled and composed on the GPU; the CPU sees canvas-sized frames.
        self._gpu_graph = gpu_graph
        if gpu_graph is not None:
            hardware_decode = (gpu_graph.hwaccel_args(), gpu_graph.download_format())
        # FFmpeg's hwaccel arguments and the software format its frames are repacked to.
        self._hardware_decode = hardware_decode
        # Frames before this point of the clip are dropped before any costly filter.
        self._from_seconds = from_seconds
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
        # rgb24, yuv420p10le and p010le are all width*height*3 bytes; 8-bit yuv420p is half.
        self._frame_size = width * height * 3 // 2 if pix_fmt == "yuv420p" else width * height * 3
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
            overlay_format = ":format=yuv420p10" if self._ten_bit else ""
            # WHY (#2792): the overlay's output format was left to negotiation, and
            # libplacebo after it negotiated a graph that never output a frame: on
            # FFmpeg 6.1 with libplacebo v6.338 every blur-fill clip decoded to
            # nothing and FFmpeg still exited 0. Measured on one clip, 109 frames
            # asked: blur fill alone 109, pad fill + libplacebo 109, blur fill +
            # libplacebo 0, blur fill + format + libplacebo 109.
            pinned = "yuv420p10le" if self._ten_bit else "yuv420p"
            self._use_filter_complex = True
            return [
                "split[_bg][_fg]",
                self._blur_background(),
                f"[_fg]scale={self._width}:{self._height}:force_original_aspect_ratio=decrease:flags=lanczos[_sharp]",
                f"[_blurred][_sharp]overlay=(W-w)/2:(H-h)/2{overlay_format}",
                f"format={pinned}",
            ]
        # "fit": scale down inside the frame and pad the rest black. There is
        # no face-aware crop on the video path, so anything that is not
        # "blur" lands here — which is why no such mode is offered.
        self._use_filter_complex = False
        return [
            f"scale={self._width}:{self._height}:force_original_aspect_ratio=decrease:flags=lanczos",
            f"pad={self._width}:{self._height}:(ow-iw)/2:(oh-ih)/2:black",
        ]

    def _leading_filters(self) -> list[str]:
        """Repack, rotation, privacy blur, the PTS reset and a trimmed head."""
        parts: list[str] = []
        if self._hardware_decode is not None:
            parts.append(f"format={self._hardware_decode[1]}")

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
        if self._from_seconds > 0:
            # WHY (#2709): the frames kept are the ones a whole decode gives. Timestamps
            # are not reset after the trim, so the frame-rate filter still places every
            # later frame on the grid it had; only the earlier frames skip the work.
            parts.append(f"trim=start={self._from_seconds:.6f}")
        return parts

    @property
    def _ten_bit(self) -> bool:
        return self._pix_fmt in _TEN_BIT_PIPES

    def _build_gpu_vf(self, graph: GpuFrameGraph) -> str:
        """The chain when the clip is decoded, scaled and filled on the GPU."""
        parts = ["setpts=PTS-STARTPTS"]
        if self._from_seconds > 0:
            parts.append(f"trim=start={self._from_seconds:.6f}")
        rate = self._source_frame_rate
        early_fps = rate is not None and rate >= self._fps
        if early_fps:
            parts.append(f"fps={self._fps},settb=1/{self._fps}")
        conversion = ",".join(
            f.removeprefix(",") for f in (self._sdr_to_hdr_filter, self._hdr_conversion) if f
        )
        source_w, source_h = graph.coded_size
        # A transfer conversion runs at whichever of source and canvas has fewer pixels.
        convert_first = conversion if source_w * source_h < self._width * self._height else ""
        parts.append(
            graph.fill(
                (self._width, self._height),
                self._scale_mode,
                convert_first=convert_first,
                converted_ten_bit=self._ten_bit,
            )
        )
        late = conversion if not convert_first else ""
        defer_fps = bool(late) and rate is not None and 0 < rate < self._fps
        if not (early_fps or defer_fps):
            parts.append(f"fps={self._fps},settb=1/{self._fps}")
        for color_filter in (late, self._colorspace_filter, self._output_pix_fmt):
            if color_filter:
                parts.append(color_filter.removeprefix(","))
        if defer_fps:
            parts.append(f"fps={self._fps},settb=1/{self._fps}")
        parts.extend(self._closing_filters())
        self._use_filter_complex = True
        return ",".join(parts)

    def _build_vf(self) -> str:
        """Build the -vf filter chain applied to every decoded clip."""
        if self._gpu_graph is not None:
            return self._build_gpu_vf(self._gpu_graph)
        parts = self._leading_filters()

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
            self._ten_bit
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

        parts.extend(self._closing_filters())
        return ",".join(parts)

    def _closing_filters(self) -> list[str]:
        """Captions, square pixels and the frame count, on the final frame grid."""
        parts: list[str] = []
        # Drawn last so the text is never scaled, padded or blurred with the
        # source, and lands in target-frame coordinates.
        if self._caption:
            parts.extend(
                caption_filters(
                    self._caption,
                    self._width,
                    self._height,
                    is_hdr=self._ten_bit,
                    font_path=self._caption_font,
                    frame_window=self._caption_window,
                    drawtext=drawtext_available(),
                )
            )

        # Square pixels
        parts.append("setsar=1")

        if self._frame_limit is not None:
            # WHY (#2347): a clip lasts as long as its container, which counts the
            # audio. A video stream that ends first emitted fewer frames than its
            # WAV holds, and every later clip's sound ran ahead of its picture.
            # Holding the last picture gives exactly the frames the WAV is cut to.
            parts.append("tpad=stop_mode=clone:stop=-1")
        return parts

    def __iter__(self) -> Iterator[np.ndarray]:
        """Yield independent, read-only frames that callers may retain."""
        return self._iter_frames(reuse_buffer=False)

    def iter_borrowed_frames(
        self, *, read_ahead: bool = False
    ) -> Generator[np.ndarray, None, str | None]:
        """Yield read-only views valid until the next complete frame arrives.

        Exhaustion preserves the last frame for crossfade holds. Copy frames
        before advancing if they must remain available beyond the next yield.
        Read-ahead uses three slots; the synchronous path uses two.
        """
        return self._iter_frames(reuse_buffer=True, read_ahead=read_ahead)

    def _command(self) -> list[str]:
        """The FFmpeg command that decodes the clip to the pipe, its audio to a WAV."""
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
        return [
            "ffmpeg",
            # WHY (#2345): a software retry decodes into the WAV the failed
            # attempt left behind. Without -y FFmpeg refused to overwrite it and
            # exited before its first frame; without -nostdin it could instead
            # wait on an overwrite prompt nobody sees.
            "-y",
            "-nostdin",
            # stderr goes to a file read only when a clip ends short: warnings and
            # errors, without a progress line per frame.
            "-nostats",
            "-loglevel",
            "warning",
            "-filter_threads",
            filter_threads,
            "-filter_complex_threads",
            filter_threads,
            "-threads",
            str(threads),
            *seek_args,
            *self._hwaccel_args(),
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
            # The graph's fps filter sets the rate; a trimmed head is dropped rather
            # than refilled with copies of the first frame kept.
            *(["-fps_mode", "passthrough"] if self._from_seconds > 0 else ["-r", str(self._fps)]),
            *video_limit,
            "pipe:1",
            *audio_args,
        ]

    def _iter_frames(
        self, reuse_buffer: bool, read_ahead: bool = False
    ) -> Generator[np.ndarray, None, str | None]:
        """Yield the clip's frames; a clip that ends short returns what FFmpeg said.

        The return value reaches the caller as ``StopIteration.value``.
        """
        cmd = self._command()
        logger.debug(f"FrameDecoder cmd: {' '.join(cmd)}")
        # WHY (#2792): a clip that decoded to nothing used to leave no trace, since
        # FFmpeg exited 0 and stderr went to DEVNULL. A file, never a pipe, so FFmpeg
        # cannot block on it the way it blocks on a pipe nobody reads (#2709).
        stderr = tempfile.TemporaryFile()  # noqa: SIM115
        proc = subprocess.Popen(  # noqa: S603, S607
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=stderr,
            bufsize=self._frame_size,
        )
        assert proc.stdout is not None  # noqa: S101
        # Popen's positive bufsize gives this binary pipe a BufferedReader.
        pipe = cast(BufferedReader, proc.stdout)

        reader = _FrameReadAhead(pipe, self._frame_size) if read_ahead else None
        raw_frames = reader.frames() if reader is not None else self._raw_frames(pipe, reuse_buffer)
        decoded = 0
        try:
            with owned_child(proc):
                for decoded, raw in enumerate(raw_frames, start=1):
                    frame = self._frame_view(raw)
                    frame.setflags(write=False)
                    self._finish_bounded_output(proc, decoded)
                    yield frame
                self._check_hardware_decode(proc)
                if decoded == 0 or (self._frame_limit is not None and decoded < self._frame_limit):
                    return self._why_short(proc, stderr)
                return None
        finally:
            stderr.close()
            # WHY (#2709): a decoder closed before its last frame leaves FFmpeg blocked
            # writing to a full pipe, where SIGTERM cannot reach it, so every early stop
            # waited out the whole terminate grace. A pipe nobody reads is closed first
            # (the next write fails and FFmpeg exits); a read-ahead reader drains it
            # instead, since it may still be inside a read.
            if reader is not None:
                reader.stop()
            else:
                proc.stdout.close()
            # Stop the writer before joining a reader blocked on its pipe.
            stop_owned_process(proc)
            try:
                raw_frames.close()
            finally:
                proc.stdout.close()

    def _frame_view(self, raw: bytes | bytearray) -> np.ndarray:
        if self._ten_bit:
            # WHY: Keep as flat uint16 — YUV planar can't reshape to (H,W,3).
            # Crossfade blends each sample independently which works for all planes.
            # The array retains `raw`; body writes, previews and crossfades
            # only read it. Keep the same bytes-backed view as SDR rather
            # than copying another 25 MB for every 4K HDR frame.
            return np.frombuffer(raw, dtype=np.uint16)
        if self._pix_fmt == "yuv420p":
            # WHY: SDR stays planar from decoder to encoder, so no RGB
            # round trip. Flat uint8: Y plane, then U, then V.
            return np.frombuffer(raw, dtype=np.uint8)
        return np.frombuffer(raw, dtype=np.uint8).reshape(self._height, self._width, 3)

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

    def _hwaccel_args(self) -> list[str]:
        if self._hardware_decode is None:
            return []
        # A decode error ends the run, so the clip is decoded again in software rather
        # than played with the frames a hardware decoder skipped.
        return ["-xerror", *self._hardware_decode[0]]

    @staticmethod
    def _why_short(proc: subprocess.Popen[bytes], stderr: IO[bytes]) -> str:
        """FFmpeg's last lines about this clip, once it has finished writing them."""
        try:
            status: int | None = proc.wait(timeout=_STDERR_WAIT_SECONDS)
        except subprocess.TimeoutExpired:
            status = None
        stderr.seek(0)
        lines = [
            line.strip()
            for line in stderr.read().decode(errors="replace").splitlines()
            if line.strip() and not any(noise in line for noise in _STDERR_NOISE)
        ]
        said = " | ".join(lines[-_STDERR_LINES:]) or "nothing"
        exit_note = "still running" if status is None else f"exit {status}"
        return f"FFmpeg ({exit_note}) said: {said}"

    def _check_hardware_decode(self, proc: subprocess.Popen[bytes]) -> None:
        if self._hardware_decode is None:
            return
        try:
            status = proc.wait(timeout=AUDIO_FINISH_SECONDS)
        except subprocess.TimeoutExpired:
            return
        if status != 0:
            raise HardwareDecodeFailed(f"Hardware decoding of {self._clip_path.name} failed")

    def _finish_bounded_output(self, proc: subprocess.Popen[bytes], decoded: int) -> None:
        # The assembler closes this generator after its last picture.
        # Both outputs are bounded, so let the WAV finish before that
        # close can SIGTERM a still-writing audio producer.
        if self._frame_limit is None or decoded != self._frame_limit:
            return
        try:
            status = proc.wait(timeout=AUDIO_FINISH_SECONDS)
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"Frame decoder did not finish the clip's audio within "
                f"{AUDIO_FINISH_SECONDS:g} s of its last picture"
            ) from None
        if status != 0:
            if self._hardware_decode is not None:
                raise HardwareDecodeFailed(f"Hardware decoding of {self._clip_path.name} failed")
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
    planar_sdr: bool = False,
    from_seconds: float = 0.0,
    hdr_pipe_format: str = "yuv420p10le",
) -> FrameDecoder:
    """Create a FrameDecoder with per-clip normalization filters.

    SDR frames come as rgb24 unless `planar_sdr` asks for yuv420p, which the
    streaming encoder takes without converting. HDR frames come as
    `hdr_pipe_format`: P010 when a hardware encoder takes them as they are.
    """
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
        source_types[clip_idx] = detect_hdr_type(clip.path, probe_cache=probe_cache)
        source_primaries[clip_idx] = detect_color_primaries(clip.path, probe_cache=probe_cache)
        ctx = SimpleNamespace(
            hdr_type=target_type,
            pix_fmt="yuv420p10le" if hdr_type else "yuv420p",
            clip_hdr_types=source_types,
            clip_primaries=source_primaries,
            colorspace_filter=get_colorspace_filter(target_type),
        )

    # Title videos may be pre-encoded, but only an exact transfer match may
    # bypass conversion. The shared resolver makes the same decision for all clips.
    hdr_conversion, colorspace_filter, output_pix_fmt, sdr_to_hdr_filter, _ = resolve_clip_hdr(
        clip_idx, ctx, hdr_type
    )
    pix_fmt = hdr_pipe_format if hdr_type else ("yuv420p" if planar_sdr else "rgb24")
    if hdr_type and output_pix_fmt:
        output_pix_fmt = f",format={pix_fmt}"
    # The same maths on the GPU where libplacebo proves it gives zscale's picture.
    hdr_conversion = transfer_conversion(
        hdr_conversion, clip.path, clip_idx, ctx, hdr_type, pix_fmt
    )
    logger.info(
        f"Decoder[{clip_idx}] pix={pix_fmt} title={is_title} hdr_type={hdr_type} "
        f"sdr2hdr={bool(sdr_to_hdr_filter)} {clip.path.name}"
    )

    audio_output = None
    if audio_work_dir:
        audio_output = audio_work_dir / f"clip_{clip_idx}_audio.wav"

    source_size, source_frame_rate = _source_properties(clip.path, probe_cache)
    capabilities = getattr(ctx, "decode_capabilities", None)
    privacy_blur = privacy_mode and not is_title
    # Privacy's frosted glass and a forced turn are shaped at source size, on the CPU.
    gpu_graph = (
        None
        if privacy_blur or rotation
        else gpu_frame_graph_for_path(clip.path, capabilities, probe_cache)
    )
    return FrameDecoder(
        gpu_graph=gpu_graph,
        hardware_decode=(
            None if gpu_graph else hardware_decode_for(clip.path, capabilities, probe_cache)
        ),
        clip_path=clip.path,
        probe_cache=probe_cache,
        width=width,
        height=height,
        fps=fps,
        pix_fmt=pix_fmt,
        rotation=rotation,
        privacy_blur=privacy_blur,
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
        from_seconds=from_seconds,
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

    def stop(self) -> None:
        """Stop handing out frames; the reader drains the pipe until its writer exits."""
        self._stopped.set()

    def _produce(self) -> None:
        try:
            while not self._stopped.is_set():
                try:
                    slot = self._available.get(timeout=0.1)
                except Empty:
                    continue
                if self._pipe.readinto(slot) != self._frame_size:
                    return
                self._offer(slot)
            self._drain()
        except BaseException as exc:
            # Report worker failures on the consuming thread instead of hanging it.
            self._offer(exc)
        finally:
            self._offer(None)

    def _drain(self) -> None:
        # A writer blocked on a full pipe never sees SIGTERM; reading on keeps it moving.
        scratch = bytearray(self._frame_size)
        while self._pipe.readinto(scratch):
            pass

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
