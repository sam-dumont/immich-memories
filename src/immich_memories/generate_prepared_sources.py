"""Reuse a source an earlier run already prepared to the same recipe (#2032, #2452).

Reusing a clip prepared from other bytes, another window, another route or another
encoding puts the wrong picture in a film, which is worse than preparing it again.
So the key is built from the inputs preparation actually reads, not from a list of
fields someone judged relevant:

- the route, decided by `generate_downloads.preparation_route`, the same function
  source preparation dispatches on: photo, video still, Live stitch or video cut;
- the whole clip as selection handed it over, asset included (its checksum and
  times, the edited flag, the Live companion and burst ids, faces, place, date),
  and the size and mtime of a local file the run reads instead of downloading;
- for an edited photo, the edit itself as Immich holds it (`_immich_edit`): Immich
  keeps `updatedAt` and `isEdited` when an edit is replaced, so nothing else on the
  asset tells a rotated picture from a mirrored one (#2479);
- the whole render directive, and the timing preparation resolves from it: the cut
  window (`generate_clips.segment_window`) and the time a still stays on screen
  (`generate_clips.photo_hold_seconds`, else `photos.duration`);
- which of Immich's files a still is rendered from (`photo_pipeline.photo_rendition`);
- the canvas, the output format and the scale mode this run resolved;
- the people the film is about, since a still's move heads for them;
- the configuration, every section but those preparation never reads, which
  hold credentials, addresses and storage paths (`_UNREAD_SECTIONS`);
- what this machine's FFmpeg and encoders can do, which picks the encoder and
  the HDR tone-map route;
- `RECIPE_VERSION`, the Live render versions and the app version, so a code change
  never reuses an older rendering. Bump `RECIPE_VERSION` when preparation changes
  between releases.

Privacy mode is not in it: it blurs and relabels at assembly, after preparation.

A preparation that noted a fallback (`processing/preparation_fallbacks.py`) is
never banked: the fallback serves this film, and the next run tries again.

A reused segment is labelled (rotation, mood, music flag, place) by the same code
that labels a fresh one.
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
from typing import TYPE_CHECKING, Any

from immich_memories import __version__
from immich_memories.generate_downloads import SourceRoute, preparation_route
from immich_memories.processing.assembly_config import AssemblyClip
from immich_memories.processing.preparation_fallbacks import watching_fallbacks
from immich_memories.security import private_temp_dir

if TYPE_CHECKING:
    from immich_memories.analysis.runtime.plan import EditorialSelection
    from immich_memories.api.models import VideoClipInfo
    from immich_memories.cache.prepared_source_bank import BankedSource, PreparedSourceBank
    from immich_memories.config.loader import Config
    from immich_memories.generate import GenerationParams

logger = logging.getLogger(__name__)

RECIPE_VERSION = "prepared-source-v6"

# Config sections source preparation never reads. They are left out because several
# carry credentials, addresses or storage paths, not because they were judged
# harmless field by field; every other section is in the key whole.
_UNREAD_SECTIONS: dict[str, Any] = {
    "server": True,
    "immich": True,
    "render": True,
    "cache": True,
    "database": True,
    "llm": True,
    "musicgen": True,
    "ace_step": True,
    "auth": True,
    "notifications": True,
    "upload": True,
    "automation": True,
    "inference": True,
    "triage": True,
    "free_text": True,
    "network": True,
    # Where the film is written, not what any source looks like.
    "output": {"directory", "min_free_space_gb"},
}


@dataclass(frozen=True)
class PreparationRequest:
    """One selected source, as this run would prepare it."""

    params: GenerationParams
    clip: VideoClipInfo
    directive: EditorialSelection | None
    output_dir: Path
    # This run's own scratch directory, where its cut segments live until assembly.
    scratch: Path | None = None


def _local_source(local_path: str | None) -> dict[str, Any] | None:
    if not local_path:
        return None
    path = Path(local_path)
    try:
        stat = path.stat()
    except OSError:
        return {"path": local_path, "missing": True}
    return {"path": local_path, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


class EditUnreadable(ValueError):
    """An edited photo whose edit Immich could not tell: it is prepared, never reused."""


def _immich_edit(request: PreparationRequest) -> list[dict[str, Any]] | None:
    """The edit an edited photo is rendered with, as Immich's editor holds it.

    Only an edited asset is asked about, so an unedited library sends no extra
    request. Each edit keeps its action and parameters in Immich's order; its id
    is left out, since saving the same edit again renders the same picture.
    """
    asset = request.clip.asset
    if not asset.is_edited:
        return None
    import httpx

    from immich_memories.api.access_clients import AccountReadFailed
    from immich_memories.api.immich import ImmichAPIError

    client = request.params.client
    if client is None:
        raise EditUnreadable("no Immich client to read the edit from")
    try:
        edits = client.get_asset_edits(asset.id)
    except (ImmichAPIError, AccountReadFailed, httpx.HTTPError, OSError) as exc:
        # A server that cannot say which edit it renders gets a fresh preparation:
        # reusing a guess could put the old edit in the film.
        raise EditUnreadable("Immich did not tell this photo's edit") from exc
    return [{"action": edit.get("action"), "parameters": edit.get("parameters")} for edit in edits]


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


def _timing(request: PreparationRequest) -> dict[str, Any]:
    """The window and the hold preparation resolves, by the functions it resolves them with."""
    from immich_memories.generate_clips import photo_hold_seconds, segment_window

    params, clip, directive = request.params, request.clip, request.directive
    hold = photo_hold_seconds(params, clip, directive)
    return {
        "window": list(segment_window(params, clip)),
        "photo_seconds": params.config.photos.duration if hold is None else hold,
    }


def _rendering(request: PreparationRequest) -> dict[str, Any]:
    from immich_memories.photos.photo_pipeline import photo_rendition
    from immich_memories.processing.editorial_live_render import (
        FRAME_QUANTIZATION,
        RENDER_VERSION,
    )
    from immich_memories.processing.output_canvas import resolve_generation_canvas

    params = request.params
    return {
        "rendition": photo_rendition(request.clip.asset),
        "canvas": dataclasses.asdict(resolve_generation_canvas(params)),
        "output_format": params.output_format,
        "output_crf": params.output_crf,
        "scale_mode": params.scale_mode or params.config.defaults.scale_mode,
        # A still moves at the film's own rate (#2475).
        "photo_fps": params.photo_fps,
        # ... and in the film's own transfer, once its videos settle it (#2709).
        "photo_transfer": None if params.photo_transfer is None else params.photo_transfer.value,
        "live": {"render": RENDER_VERSION, "frames": FRAME_QUANTIZATION},
    }


def preparation_identity(request: PreparationRequest) -> dict[str, Any]:
    """Everything source preparation reads, as plain JSON values."""
    from immich_memories.generate_photos import memory_subjects

    clip, directive, config = request.clip, request.directive, request.params.config
    return {
        "recipe": RECIPE_VERSION,
        "app": __version__,
        "route": preparation_route(clip, directive, config),
        "clip": clip.model_dump(mode="json"),
        "edit": _immich_edit(request),
        "local_source": _local_source(clip.local_path),
        "directive": None if directive is None else dataclasses.asdict(directive),
        "timing": _timing(request),
        "rendering": _rendering(request),
        "config": config.model_dump(mode="json", exclude=_UNREAD_SECTIONS),
        "machine": _machine(config),
        # A still's move heads for the people the film is about (#2440).
        "subjects": sorted(memory_subjects(request.params)),
    }


def preparation_key(request: PreparationRequest) -> str:
    """The bank key: a SHA-256 of the canonical identity."""
    encoded = json.dumps(
        preparation_identity(request), sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


def _scratch(request: PreparationRequest) -> Path:
    return request.scratch if request.scratch is not None else private_temp_dir("clips")


def _place(path: Path, request: PreparationRequest) -> dict[str, str] | None:
    """Where the run keeps this file, so a reused copy lands where a fresh one would."""
    if path.is_relative_to(request.output_dir):
        return {"root": "output", "relative": path.relative_to(request.output_dir).as_posix()}
    if path.is_relative_to(_scratch(request)):
        return {"root": "scratch"}
    return None


def _destination(request: PreparationRequest, facts: Mapping[str, Any]) -> Path:
    place = facts["place"]
    output_dir = request.output_dir
    if place["root"] == "output":
        target = output_dir / place["relative"]
        if not target.resolve().is_relative_to(output_dir.resolve()):
            raise ValueError("a banked prepared source would escape its run folder")
        return target
    return _scratch(request) / f"prepared_{uuid.uuid4().hex[:16]}{facts['suffix']}"


# Not stored with a banked picture: the path is the bank's own, and the faces a
# video crop frames are read for each run (a picture's move is already baked in).
_UNBANKED_ASSEMBLY_FIELDS = frozenset({"path", "known_faces"})


def _facts(
    kind: SourceRoute, fresh: AssemblyClip, request: PreparationRequest
) -> dict[str, Any] | None:
    if not fresh.path.is_file():
        return None
    place = _place(fresh.path, request)
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
    kind: SourceRoute, taken: BankedSource, dress: Callable[[Path, float], AssemblyClip]
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
    kind = preparation_route(request.clip, request.directive, request.params.config)
    try:
        key = preparation_key(request)
    except (TypeError, ValueError, AttributeError) as exc:
        # A source whose inputs cannot be written down is prepared, never reused.
        logger.debug("No prepared-source key for this source: %s", exc)
        return prepare()
    taken = bank.take(
        key,
        destination=lambda facts: _destination(request, facts),
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
        facts = _facts(kind, fresh, request)
        if facts is not None:
            bank.keep(key, fresh.path, facts)
    return fresh
