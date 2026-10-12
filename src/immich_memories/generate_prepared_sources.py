"""Reuse a source an earlier run already prepared to the same recipe (#2032).

The key is strict on purpose. Reusing a clip prepared from other bytes, another
window or another encoding would put the wrong picture in a film, which is worse
than preparing it again. So the key carries:

- the source's content identity in Immich: id, checksum, modification and update
  times, the edited flag, the Live companion, plus the size and mtime of a local
  file the run reads instead of downloading;
- everything this run's preparation reads: the clip as the editor timed it, its
  render directive, its window, the tier, the `output` and `hardware` sections,
  and what this machine's FFmpeg and encoders can do;
- for pictures rendered onto the canvas (photos, video stills, Live merges): the
  canvas, `photos`, the output format, the scale mode, the people the film is about
  (the move heads for them) and the asset metadata the render bakes in (faces for
  the pan, the place and date it carries);
- `RECIPE_VERSION` and the app version, so a code change never reuses an older
  rendering. Bump `RECIPE_VERSION` when preparation changes between releases.

A preparation that noted a fallback (`processing/preparation_fallbacks.py`) is
never banked: the fallback serves this film, and the next run tries again.

A segment's run-level labels (rotation override, mood, music flag, place) are not
in the key: they are rebuilt from the current run on reuse, by the same code that
labels a fresh segment.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from immich_memories import __version__
from immich_memories.api.models import AssetType
from immich_memories.processing.assembly_config import AssemblyClip
from immich_memories.processing.preparation_fallbacks import watching_fallbacks
from immich_memories.security import private_temp_dir

if TYPE_CHECKING:
    from immich_memories.analysis.editorial_planner import EditorialSelection
    from immich_memories.api.models import VideoClipInfo
    from immich_memories.cache.prepared_source_bank import BankedSource, PreparedSourceBank
    from immich_memories.config_loader import Config
    from immich_memories.generate import GenerationParams

logger = logging.getLogger(__name__)

RECIPE_VERSION = "prepared-source-v2"

Kind = Literal["photo", "still", "segment", "motion"]

# What makes the bytes in Immich: a change to any of these is another source.
_CONTENT_FIELDS = frozenset(
    {
        "id",
        "type",
        "checksum",
        "original_file_name",
        "original_mime_type",
        "file_modified_at",
        "updated_at",
        "is_edited",
        "live_photo_video_id",
        "duration_seconds",
        "width",
        "height",
    }
)
# What a rendered picture bakes in beyond its bytes: the pan follows the faces, and
# the clip carries the date and place it was taken.
_PICTURE_FIELDS = frozenset({"exif_info", "people", "faces", "file_created_at", "local_date_time"})
# The model's reading of a clip labels it; it never reaches the prepared bytes.
_LABEL_FIELDS = frozenset(
    {"asset", "llm_description", "llm_category", "llm_emotion", "llm_quality"}
)


@dataclass(frozen=True)
class PreparationRequest:
    """One selected source, as this run would prepare it."""

    params: GenerationParams
    clip: VideoClipInfo
    directive: EditorialSelection | None
    output_dir: Path


def preparation_kind(clip: VideoClipInfo, directive: EditorialSelection | None) -> Kind:
    """Which preparation route the source takes, mirroring `generate_clips._rendered_clip`."""
    still = directive is not None and directive.render_mode == "still"
    if clip.asset.type == AssetType.IMAGE and (not clip.live_burst_video_ids or still):
        return "photo"
    if still:
        return "still"
    if clip.editorial_live_manifest is not None or (
        clip.live_burst_video_ids and clip.live_burst_trim_points
    ):
        return "motion"
    return "segment"


def _local_source(local_path: str | None) -> dict[str, Any] | None:
    if not local_path:
        return None
    path = Path(local_path)
    try:
        stat = path.stat()
    except OSError:
        return {"path": local_path, "missing": True}
    return {"path": local_path, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def _machine(config: Config) -> dict[str, Any]:
    """What this machine's FFmpeg can do decides the encoder and the HDR route."""
    from immich_memories.processing.hardware import detect_hardware_acceleration
    from immich_memories.processing.hdr_utilities import check_zscale_available

    encoders = None
    if config.hardware.enabled:
        capabilities = detect_hardware_acceleration(config.hardware.backend)
        encoders = {
            "backend": str(capabilities.backend.value),
            "h264": capabilities.supports_h264_encode,
            "h265": capabilities.supports_h265_encode,
        }
    return {"zscale": check_zscale_available(), "encoders": encoders}


def _directive(directive: EditorialSelection | None) -> dict[str, Any] | None:
    if directive is None:
        return None
    return {
        "start_time": directive.start_time,
        "end_time": directive.end_time,
        "render_mode": directive.render_mode,
        "render_frame_seconds": directive.render_frame_seconds,
    }


def _canvas_recipe(params: GenerationParams) -> dict[str, Any]:
    from immich_memories.processing.output_canvas import resolve_generation_canvas

    config = params.config
    return {
        "canvas": dataclasses.asdict(resolve_generation_canvas(params)),
        "photos": config.photos.model_dump(mode="json"),
        "output_format": params.output_format,
        "scale_mode": params.scale_mode or config.defaults.scale_mode,
    }


def preparation_identity(request: PreparationRequest) -> dict[str, Any]:
    """Everything that decides the prepared bytes, as plain JSON values."""
    params, clip, directive = request.params, request.clip, request.directive
    config = params.config
    kind = preparation_kind(clip, directive)
    identity: dict[str, Any] = {
        "recipe": RECIPE_VERSION,
        "app": __version__,
        "kind": kind,
        "source": clip.asset.model_dump(mode="json", include=set(_CONTENT_FIELDS)),
        "local_source": _local_source(clip.local_path),
        "clip": clip.model_dump(mode="json", exclude=set(_LABEL_FIELDS)),
        "directive": _directive(directive),
        "window": params.clip_segments.get(clip.asset.id),
        "encoding": {
            "tier": config.tier,
            "output": config.output.model_dump(mode="json"),
            "hardware": config.hardware.model_dump(mode="json"),
            "machine": _machine(config),
        },
    }
    if kind != "segment":
        from immich_memories.generate_photos import memory_subjects

        identity["picture"] = clip.asset.model_dump(mode="json", include=set(_PICTURE_FIELDS))
        identity["render"] = _canvas_recipe(params)
        # A still's move heads for the people the film is about (#2440).
        identity["subjects"] = sorted(memory_subjects(params))
    if kind == "motion":
        from immich_memories.processing.editorial_live_render import (
            FRAME_QUANTIZATION,
            RENDER_VERSION,
        )

        identity["live"] = {"render": RENDER_VERSION, "frames": FRAME_QUANTIZATION}
    return identity


def preparation_key(request: PreparationRequest) -> str:
    """The bank key: a SHA-256 of the canonical identity."""
    encoded = json.dumps(
        preparation_identity(request), sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


def _scratch() -> Path:
    return private_temp_dir("clips")


def _place(path: Path, output_dir: Path) -> dict[str, str] | None:
    """Where the run keeps this file, so a reused copy lands where a fresh one would."""
    if path.is_relative_to(output_dir):
        return {"root": "output", "relative": path.relative_to(output_dir).as_posix()}
    if path.is_relative_to(_scratch()):
        return {"root": "scratch"}
    return None


def _destination(output_dir: Path, facts: Mapping[str, Any]) -> Path:
    place = facts["place"]
    if place["root"] == "output":
        target = output_dir / place["relative"]
        if not target.resolve().is_relative_to(output_dir.resolve()):
            raise ValueError("a banked prepared source would escape its run folder")
        return target
    # A unique name: the shared scratch directory outlives this run and serves others.
    return _scratch() / f"prepared_{uuid.uuid4().hex[:16]}{facts['suffix']}"


# Not stored with a banked picture: the path is the bank's own, and the faces a
# video crop frames are read for each run (a picture's move is already baked in).
_UNBANKED_ASSEMBLY_FIELDS = frozenset({"path", "known_faces"})


def _facts(kind: Kind, fresh: AssemblyClip, output_dir: Path) -> dict[str, Any] | None:
    if not fresh.path.is_file():
        return None
    place = _place(fresh.path, output_dir)
    if place is None:
        return None
    facts: dict[str, Any] = {"kind": kind, "place": place, "suffix": fresh.path.suffix.lower()}
    if kind in ("segment", "motion"):
        facts["duration"] = fresh.duration
    else:
        facts["assembly"] = {
            field.name: getattr(fresh, field.name)
            for field in dataclasses.fields(AssemblyClip)
            if field.name not in _UNBANKED_ASSEMBLY_FIELDS
        }
    return facts


def _rebuilt(
    kind: Kind, taken: BankedSource, dress: Callable[[Path, float], AssemblyClip]
) -> AssemblyClip | None:
    facts = taken.facts
    try:
        if kind in ("segment", "motion"):
            return dress(taken.path, float(facts["duration"]))
        return AssemblyClip(path=taken.path, **facts["assembly"])
    except (KeyError, TypeError, ValueError):
        # A record this code cannot read back is a miss, not a failed source.
        taken.path.unlink(missing_ok=True)
        return None


def reuse_or_prepare(
    bank: PreparedSourceBank,
    request: PreparationRequest,
    *,
    prepare: Callable[[], AssemblyClip | None],
    dress: Callable[[Path, float], AssemblyClip],
) -> AssemblyClip | None:
    """Hand back the banked preparation of this source, or prepare and bank it.

    ``prepare`` is the run's own preparation. ``dress`` labels a segment from the
    current run, the way a fresh segment is labelled. A source Immich gave no
    checksum has no content identity to key on, so it is prepared every time.
    """
    if not request.clip.asset.checksum:
        return prepare()
    kind = preparation_kind(request.clip, request.directive)
    key = preparation_key(request)
    taken = bank.take(
        key,
        destination=lambda facts: _destination(request.output_dir, facts),
        accept=lambda facts: facts.get("kind") == kind,
    )
    if taken is not None:
        reused = _rebuilt(kind, taken, dress)
        if reused is not None:
            return reused
    with watching_fallbacks() as fallbacks:
        fresh = prepare()
    if fallbacks:
        # This film keeps what the fallback made; the next one tries for the real thing.
        logger.info(
            "Not keeping %s for later runs: %s", request.clip.asset.id, "; ".join(fallbacks)
        )
    elif fresh is not None:
        facts = _facts(kind, fresh, request.output_dir)
        if facts is not None:
            bank.keep(key, fresh.path, facts)
    return fresh
