"""Render one photograph as an animated video clip.

Streams frames directly to FFmpeg via stdin pipe — never holds more than
one frame in memory at a time.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Collection, Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np

from immich_memories.analysis.framing_target import picture_faces
from immich_memories.api.immich import ImmichAPIError
from immich_memories.api.models import Asset
from immich_memories.config_models_render import PhotoConfig
from immich_memories.generate_privacy import clip_location_name
from immich_memories.photos.animator import prepare_photo_source
from immich_memories.photos.encoding import photo_encoding_plan
from immich_memories.photos.ken_burns_moves import film_subject, planned_move
from immich_memories.photos.renderer import (
    KenBurnsParams,
    render_ken_burns_streaming,
)
from immich_memories.processing.assembly_config import AssemblyClip
from immich_memories.processing.clip_encoder import encoder_args_for_plan
from immich_memories.processing.encoding_plan import EncodingPlan, HdrTransfer
from immich_memories.processing.ffmpeg_runner import write_frames_to_ffmpeg
from immich_memories.processing.hardware_encode import apply_hardware_encode

if TYPE_CHECKING:
    from immich_memories.config_loader import Config
    from immich_memories.processing.hardware import HWAccelCapabilities

logger = logging.getLogger(__name__)


# How many previews the tie-break may fetch when nothing cached them. The
# photos in contention are what it is for, and a library's worth of previews
# is the cost the LLM shortlist exists to avoid.
# Scoring one photo costs an LLM round trip, so the shortlist is what actually
# determines how long a run takes. A real library produced a 1194-photo
# shortlist to place a few dozen photos, which ran for hours.
# Undated photos sort first rather than dropping out of the grouping.
# What counts as one moment when sampling photos for a content look.
# How much of a photo's score the pixels are allowed to decide. The metadata
# terms keep their meaning, but they no longer decide the whole ordering on
# their own.
def _source_photo_path(asset: Asset, work_dir: Path) -> Path:
    ext = Path(asset.original_file_name).suffix if asset.original_file_name else ".jpg"
    return work_dir / f"{asset.id}{ext}"


def _prepared_photo_pixels(raw_path: Path, target_w: int, target_h: int, work_dir: Path):
    """Decode the source into integer RGB (16-bit for gain-mapped HDR), or report it unreadable."""
    # Prepare (HEIC decode, gain map extraction for HDR).
    # WHY 1.5x (#423): the renderer samples at most output x 1.12 max zoom
    # (1.41x before #2440 dropped the pan margin), and it holds three copies of
    # whatever it is given. Measured on a 24.5 MP HEIC at 4K: 2.0x paid
    # 0.63 s and 0.32 GB per photo for pixels its own resize discarded.
    prepared = prepare_photo_source(
        raw_path,
        work_dir,
        max_size=(round(target_w * 1.5), round(target_h * 1.5)),
    )

    # Load image — 16-bit for gain-mapped HDR, 8-bit for SDR
    img = cv2.imread(str(prepared.path), cv2.IMREAD_UNCHANGED)
    if img is None:
        logger.warning(f"Failed to read {prepared.path}")
        return None
    return prepared, cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


def _ken_burns_params(
    asset: Asset,
    fps: int,
    duration: float,
    *,
    subjects: Collection[str | None] = (),
    portrait: bool = False,
) -> KenBurnsParams:
    """Reproducible per-asset move between the whole picture and its closest frame.

    ``subjects`` are the people the film is about, by name or person id: one
    makes a person film, several a group film (see ``ken_burns_moves``).
    """
    return planned_move(
        asset.id,
        picture_faces(asset, subjects),
        film_subject(subjects),
        fps=fps,
        duration=duration,
        portrait=portrait,
    )


def photo_rendition(asset: Asset) -> str:
    """Which of Immich's files a still is rendered from: its edit when it has one (#2114)."""
    return "edited" if asset.is_edited else "original"


def _download_photo(download_fn: Any, asset: Asset, raw_path: Path) -> None:
    """Download from Immich, asking for Immich's own edited render (crop, rotate,
    mirror) when the asset carries one -- never the untouched original (#2114)."""
    if photo_rendition(asset) == "edited":
        download_fn(asset.id, raw_path, edited=True)
    else:
        download_fn(asset.id, raw_path)


def render_single_photo(
    asset: Asset,
    config: PhotoConfig,
    target_w: int,
    target_h: int,
    work_dir: Path,
    download_fn: Any,
    fps: int = 30,
    *,
    source_path: Path | None = None,
    encoding_plan: EncodingPlan | None = None,
    encoding_config: Config | None = None,
    capabilities: HWAccelCapabilities | None = None,
    output_format: str | None = None,
    scale_mode: str = "blur",
    subjects: Collection[str | None] = (),
) -> AssemblyClip | None:
    """Download, prepare, render (streaming), and encode a single photo.

    `scale_mode` fills the bands around a still that does not match the canvas: its own
    blur ("blur") or black ("fit"), the same choice the film makes for its videos.
    `subjects` are the people the memory is about, by name or person id; the move
    ends on their faces.
    """
    try:
        raw_path = _source_photo_path(asset, work_dir) if source_path is None else source_path
        if source_path is None and not raw_path.exists():
            _download_photo(download_fn, asset, raw_path)
        loaded = _prepared_photo_pixels(raw_path, target_w, target_h, work_dir)
        if loaded is None:
            return None
        prepared, img = loaded
        # The prepared pixels are upright (EXIF applied), so their shape is the picture's own.
        params = _ken_burns_params(
            asset, fps, config.duration, subjects=subjects, portrait=img.shape[0] > img.shape[1]
        )

        # Stream-render to mp4 (O(1) memory — one frame at a time)
        output_path = work_dir / f"{asset.id}_photo.mp4"
        # WHY: peak_nits = headroom * 203 — varies per photo, baked into
        # the 16-bit normalization. zscale npl must match.
        peak_nits = getattr(prepared, "peak_nits", 1000) if prepared.has_gain_map else 203
        _stream_render_to_mp4(
            img,
            params,
            output_path,
            target_w,
            target_h,
            gain_map_hdr=prepared.has_gain_map,
            peak_nits=peak_nits,
            primaries=getattr(prepared, "primaries", "bt709"),
            encoding_plan=encoding_plan,
            encoding_config=encoding_config,
            capabilities=capabilities,
            output_format=output_format,
            scale_mode=scale_mode,
        )

        if not output_path.exists() or output_path.stat().st_size < 100:
            logger.warning(f"Encoding failed for {asset.id}")
            return None

        return AssemblyClip(
            path=output_path,
            duration=config.duration,
            date=asset.local_taken_at.isoformat() if asset.file_created_at else None,
            asset_id=asset.id,
            is_photo=True,
            gain_map_hdr=prepared.has_gain_map,
            latitude=asset.exif_info.latitude if asset.exif_info else None,
            longitude=asset.exif_info.longitude if asset.exif_info else None,
            location_name=clip_location_name(asset.exif_info),
        )

    except (ImmichAPIError, OSError, subprocess.SubprocessError, ValueError) as e:
        logger.warning(f"Failed to render photo {asset.id}: {e}")
        return None


# sRGB and BT.709 SDR share their range and near enough their curve: only the
# matrix changes, and the tags say so to every later decoder.
_SDR_CHAIN = (
    "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p"
    ",setparams=range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709"
)


def photo_filter_chain(
    *,
    gain_map_hdr: bool,
    has_zscale: bool,
    peak_nits: int,
    primaries: str,
    hdr_film: bool = True,
) -> tuple[str, str]:
    """The pipe format and filter chain for one photo clip.

    A gain-mapped source arrives as 16-bit linear at its own peak and leaves as
    PQ. An 8-bit sRGB source leaves as PQ at 203 nits for an HDR clip, and as
    BT.709 SDR otherwise.
    """
    if not gain_map_hdr and not hdr_film:
        # WHY (#2344): a source that was never HDR must not pass through PQ and
        # back. The tone map on the way down dimmed white 235 to 184 and lifted
        # the blacks.
        return "rgb24", _SDR_CHAIN
    if not has_zscale:
        # WHY: without zscale neither transfer conversion is possible. Render
        # plain SDR rather than tagging untransformed pixels as HDR.
        logger.warning("zscale not available — rendering photo as SDR")
        return "rgb24", _SDR_CHAIN
    if gain_map_hdr:
        return "rgb48le", (
            f"zscale=t=smpte2084:tin=linear"
            f":p=bt2020:pin={primaries}"
            f":m=bt2020nc:min=bt709"
            f":npl={peak_nits}"
            f",format=yuv420p10le"
        )
    # A photograph with no gain map still gets PQ, at SDR reference white.
    return "rgb24", (
        "zscale=t=smpte2084:tin=iec61966-2-1"
        ":p=bt2020:pin=bt709"
        ":m=bt2020nc:min=bt709"
        ":npl=203"
        ",format=yuv420p10le"
    )


def _at_pipe_depth(img: np.ndarray, *, sixteen_bit: bool) -> np.ndarray:
    """The source at the pipe's integer depth, so the renderer works in it directly.

    WHY (#1527): the renderer used to receive float32, 12 bytes a pixel, and every
    frame was scaled, clipped and cast back to integers: at 4K that held the source,
    its resized copy and its blur as floats, plus four frame-sized copies. OpenCV
    resizes, blurs and warps 8- and 16-bit images natively and rounds as it goes.
    8 to 16 bits is exact (x257); 16 to 8 bits truncates as the float path did.
    """
    if sixteen_bit and img.dtype == np.uint8:
        return img.astype(np.uint16) * 257
    if not sixteen_bit and img.dtype == np.uint16:
        return (img.astype(np.uint32) * 255 // 65535).astype(np.uint8)
    return img


def _stream_render_to_mp4(
    img: np.ndarray,
    params: KenBurnsParams,
    output_path: Path,
    target_w: int,
    target_h: int,
    gain_map_hdr: bool = False,
    peak_nits: int = 203,
    primaries: str = "bt709",
    encoding_plan: EncodingPlan | None = None,
    encoding_config: Config | None = None,
    capabilities: HWAccelCapabilities | None = None,
    output_format: str | None = None,
    scale_mode: str = "blur",
) -> None:
    """Render Ken Burns frames and stream directly to FFmpeg.

    Preserves HDR in HEVC only for a gain-mapped source in an HDR film.

    For gain-mapped HDR sources (16-bit linear from Apple gain map),
    pipes rgb48le and uses zscale tin=linear. For SDR sources (8-bit sRGB),
    pipes rgb24 and uses zscale tin=iec61966-2-1.

    Streams one frame at a time — O(1) memory.
    """
    from immich_memories.processing.hdr_utilities import (
        check_zscale_available,
        get_hdr_conversion_filter,
    )

    has_zscale = check_zscale_available()
    # Source HDR is known only after decoding its gain map. Filter availability
    # cannot tell us whether the photograph or the requested film needs HDR.
    plan = encoding_plan or photo_encoding_plan(
        encoding_config,
        transfer=HdrTransfer.PQ if has_zscale and gain_map_hdr else HdrTransfer.NONE,
        capabilities=capabilities,
        format_override=output_format,
    )
    encoder_args = encoder_args_for_plan(plan, frame_size=(target_w, target_h))
    pix_fmt, vf = photo_filter_chain(
        gain_map_hdr=gain_map_hdr,
        has_zscale=has_zscale,
        peak_nits=peak_nits,
        primaries=primaries,
        hdr_film=plan.hdr,
    )
    if has_zscale and (gain_map_hdr or plan.hdr):
        vf += get_hdr_conversion_filter(
            "pq", plan.target_transfer.value if plan.hdr else "sdr", required=True
        )

    source = _at_pipe_depth(img, sixteen_bit=pix_fmt == "rgb48le")

    def _frames() -> Iterator[bytes]:
        for frame in render_ken_burns_streaming(
            source, target_w, target_h, params, scale_mode=scale_mode
        ):
            yield frame.tobytes()

    returncode, stderr_text = write_frames_to_ffmpeg(
        apply_hardware_encode(
            [
                "ffmpeg",
                "-y",
                "-f",
                "rawvideo",
                "-pix_fmt",
                pix_fmt,
                "-s",
                f"{target_w}x{target_h}",
                "-r",
                str(params.fps),
                "-i",
                "pipe:0",
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=48000:cl=stereo",
                "-vf",
                vf,
                *encoder_args,
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-t",
                str(params.duration),
                "-shortest",
                str(output_path),
            ],
            pixel_format=plan.pixel_format,
        ),
        _frames(),
        wait_timeout=300,
    )

    if returncode != 0:
        raise RuntimeError(f"Photo FFmpeg encoding failed (exit {returncode}): {stderr_text}")
