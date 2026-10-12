"""Photo rendering, budget allocation, and clip merging for generate pipeline."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from immich_memories.processing.assembly_config import (
    AssemblyClip,
)

if TYPE_CHECKING:
    from immich_memories.api.models import Asset, VideoClipInfo
    from immich_memories.generate import GenerationParams

logger = logging.getLogger(__name__)


def detect_photo_resolution(params: GenerationParams) -> tuple[int, int]:
    """Return the same memoized canvas used by final assembly."""
    from immich_memories.processing.output_canvas import resolve_generation_canvas

    canvas = resolve_generation_canvas(params)
    return canvas.width, canvas.height


def memory_subjects(params: GenerationParams) -> tuple[str, ...]:
    """The people the film is about, by name; empty for a film about nobody in particular."""
    named = (*params.memory_people, params.person_name)
    # memory_people arrive casefolded and person_name as typed: one person, not two.
    return tuple(dict.fromkeys(" ".join(name.split()).casefold() for name in named if name))


def with_face_boxes(asset: Asset, client: Any) -> Asset:
    """The asset with Immich's face boxes on it, for the move to frame.

    Immich's asset and search endpoints name the people in a picture but carry
    no geometry for them; the boxes come from their own endpoint, one request
    per still. A failed read leaves the still without faces: it moves toward
    its centre rather than failing the film. That covers every way the read can
    fail: Immich's refusal, a dropped connection, a reply this code cannot parse,
    and a household client reporting that the owning account could not read it.
    """
    import httpx

    from immich_memories.api.access_clients import AccountReadFailed
    from immich_memories.api.immich import ImmichAPIError

    if client is None or asset.faces or any(person.faces for person in asset.people):
        return asset
    try:
        faces = list(client.get_asset_faces(asset.id))
    except (ImmichAPIError, AccountReadFailed, httpx.HTTPError, OSError, ValueError) as exc:
        logger.debug("No face boxes for %s: %s", asset.id, type(exc).__name__)
        return asset
    return asset.model_copy(update={"faces": faces}) if faces else asset


def render_photo_as_clip(
    clip: VideoClipInfo,
    params: GenerationParams,
    output_dir: Path,
    *,
    source_path: Path | None = None,
    duration_seconds: float | None = None,
) -> AssemblyClip | None:
    """Download and render a photo as an animated video clip for assembly.

    Uses the same rendering pipeline as photo_pipeline.render_single_photo:
    downloads from Immich, prepares the source (HEIC decode, gain map),
    then streams Ken Burns frames to FFmpeg.
    """
    from immich_memories.config_models_render import normalize_scale_mode
    from immich_memories.photos.photo_pipeline import render_single_photo
    from immich_memories.processing.hardware import (
        HWAccelCapabilities,
        detect_hardware_acceleration,
    )

    if not params.client and source_path is None:
        logger.warning("No Immich client — cannot render photo clip")
        return None

    photo_dir = output_dir / "photos"
    photo_dir.mkdir(exist_ok=True)

    target_w, target_h = detect_photo_resolution(params)
    photo_config = params.config.photos
    if duration_seconds is not None:
        photo_config = photo_config.model_copy(update={"duration": duration_seconds})

    result = render_single_photo(
        asset=with_face_boxes(clip.asset, params.client),
        config=photo_config,
        target_w=target_w,
        target_h=target_h,
        work_dir=photo_dir,
        download_fn=params.client.download_asset if params.client else None,
        source_path=source_path,
        encoding_config=params.config,
        output_format=params.output_format,
        capabilities=(
            detect_hardware_acceleration(params.config.hardware.backend)
            if params.config.hardware.enabled
            else HWAccelCapabilities()
        ),
        scale_mode=normalize_scale_mode(params.scale_mode or params.config.defaults.scale_mode),
        subjects=memory_subjects(params),
    )
    if result is None:
        logger.warning(f"Failed to render photo {clip.asset.id}")
    return result


def _render_video_frame_as_clip(
    clip: VideoClipInfo,
    params: GenerationParams,
    output_dir: Path,
    *,
    video_path: Path,
    frame_seconds: float,
) -> AssemblyClip | None:
    """Sample one chosen video frame and render it through the photo pipeline."""
    from immich_memories.processing.frame_sampling import extract_frame_at

    photo_dir = output_dir / "photos"
    photo_dir.mkdir(exist_ok=True)
    target_w, _target_h = detect_photo_resolution(params)
    frame_path = extract_frame_at(
        video_path,
        timestamp=frame_seconds,
        width=clip.width or target_w,
        output_path=photo_dir / f"{clip.asset.id}_editorial-frame.jpg",
    )
    if frame_path is None:
        logger.warning("Failed to sample editorial still for %s", clip.asset.id)
        return None
    segment = params.clip_segments.get(clip.asset.id)
    duration_seconds = None if segment is None else segment[1] - segment[0]
    return render_photo_as_clip(
        clip,
        params,
        output_dir,
        source_path=frame_path,
        duration_seconds=duration_seconds,
    )
