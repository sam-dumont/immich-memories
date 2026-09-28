"""Render a saved cut, or one of its revisions, without selecting anything again.

`immich-memories runs render` and the web client's export both come here, and from here to
`generate_memory`, the same engine a fresh `generate` ends in. The cut's own render inputs are
read back (see `processing/render_inputs.py`), the revision's edits go through the owner-edit
projection, and the film is recorded as a new run on the same attempt.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from immich_memories.api.models import VideoClipInfo
from immich_memories.filename_builder import build_memory_output_path, name_after_recipe
from immich_memories.generate import GenerationParams, generate_memory
from immich_memories.operations.phases import OperationalPhase
from immich_memories.operations.revision_render import RenderUnavailable, project_revision
from immich_memories.processing.editorial_timing import timing_policy_for_params
from immich_memories.processing.encoding_plan import resolve_output_selection
from immich_memories.processing.output_canvas import resolve_output_canvas
from immich_memories.processing.render_inputs import CutTitles, read_cut_titles, read_render_inputs
from immich_memories.timeperiod import DateRange
from immich_memories.titles.film_title import resolve_film_title

if TYPE_CHECKING:
    from collections.abc import Callable

    from immich_memories.analysis.motion_rendering import MotionRendering
    from immich_memories.api.models import Asset
    from immich_memories.api.sync_client import SyncImmichClient
    from immich_memories.config_loader import Config
    from immich_memories.operations.cut_revisions import CutRevision
    from immich_memories.processing.added_material import LiveMotion
    from immich_memories.tracking.models import RunMetadata


@dataclass(frozen=True)
class CutRenderRequest:
    """The output choices a render makes, the same ones `generate` takes; None means config."""

    title: str | None = None
    subtitle: str | None = None
    llm_title: bool | None = None
    transition: str | None = None
    output_resolution: str | None = None
    output_orientation: str | None = None
    scale_mode: str | None = None
    output_format: str | None = None
    quality: str | None = None
    add_date_overlay: bool = False
    add_place_overlay: bool = False
    privacy_mode: bool = False
    music_path: Path | None = None
    music_volume: float = 0.5
    no_music: bool = False
    upload: bool = False
    album: str | None = None


def _fetcher(client: SyncImmichClient | None) -> Callable[[str], VideoClipInfo | None]:
    def fetch(asset_id: str) -> VideoClipInfo | None:
        if client is None:
            return None
        asset = client.get_asset(asset_id)
        return VideoClipInfo(
            asset=asset,
            duration_seconds=asset.duration_seconds or 0.0,
            width=asset.width,
            height=asset.height,
        )

    return fetch


def _live_motion(config: Config, client: SyncImmichClient | None) -> LiveMotion:
    """Stitch an added Live Photo's motion the way the cut's own Live shots were stitched."""

    def stitch(asset: Asset) -> MotionRendering | None:
        if client is None or not asset.live_photo_video_id:
            return None
        from immich_memories.analysis.motion_rendering import motion_renderings

        companion = client.get_asset(asset.live_photo_video_id)
        found = motion_renderings([asset], config, companion_assets={companion.id: companion})
        return found.get(asset.id)

    return stitch


def _date_range(run: RunMetadata) -> DateRange:
    start = run.date_range_start or run.created_at.date()
    end = run.date_range_end or start
    return DateRange(datetime.combine(start, time.min), datetime.combine(end, time.max))


def _params(
    config: Config, client: SyncImmichClient | None, run: RunMetadata, policy: dict[str, Any]
) -> GenerationParams:
    return GenerationParams(
        clips=[],
        output_path=config.output.output_path,
        config=config,
        client=client,
        transition=policy["transition"],
        transition_duration=policy["transition_duration"],
        memory_type=run.memory_type,
        person_name=run.person_name,
        date_start=run.date_range_start,
        date_end=run.date_range_end,
        memory_key_override=run.memory_key,
        memory_category=run.memory_category,
        memory_people=run.memory_people,
        target_duration_seconds=policy["target_seconds"],
        include_photos=False,
        completed_operational_phase=OperationalPhase.SELECTION,
    )


def _apply_request(
    params: GenerationParams,
    request: CutRenderRequest,
    run: RunMetadata,
    date_range: DateRange,
    cut_clips: list[VideoClipInfo],
    saved: CutTitles | None,
) -> None:
    config = params.config
    params.memory_preset_params = dict(saved.preset_params) if saved is not None else {}
    params.transition = request.transition or params.transition
    params.output_resolution = request.output_resolution
    params.output_orientation = request.output_orientation
    params.scale_mode = request.scale_mode
    params.output_format = request.output_format
    if request.quality:
        # As generate does: the flag overrides the config, and the preset decides the CRF. Validated,
        # so a retired word (`medium`, `low`) lands on the preset it now means.
        config.output = config.output.model_validate(
            config.output.model_dump() | {"quality": request.quality, "crf": None}
        )
    params.add_date_overlay = request.add_date_overlay
    params.add_place_overlay = request.add_place_overlay
    params.privacy_mode = request.privacy_mode
    params.music_path = request.music_path
    params.music_volume = request.music_volume
    params.no_music = request.no_music
    params.upload_enabled = request.upload
    params.upload_album = request.album or config.upload.album_name
    # The title `generate` gave the cut stands (a special day's catalogue name, a trip's place)
    # unless this render names the film itself or asks the model again.
    if saved is not None and saved.title and request.title is None is request.llm_title:
        params.title, params.subtitle, params.title_source = (
            saved.title,
            request.subtitle or saved.subtitle,
            saved.source,
        )
        return
    params.title, params.subtitle, source = resolve_film_title(
        enabled=request.llm_title,
        title_override=request.title,
        subtitle_override=request.subtitle,
        clips=cut_clips,
        config=config,
        memory_type=run.memory_type,
        date_range=date_range,
        person_names=list(run.memory_people),
        memory_preset_params=params.memory_preset_params,
    )
    params.title_source = source.value if source is not None else None


def render_saved_cut(
    *,
    config: Config,
    client: SyncImmichClient | None,
    run: RunMetadata,
    attempt_dir: Path,
    revision: CutRevision | None,
    request: CutRenderRequest,
    progress_callback: Callable[[str, float, str], None] | None = None,
    phase_callback: Callable[[Any], None] | None = None,
) -> Path:
    """Render this cut (or revision) through `generate_memory`; return the film's path."""
    inputs = read_render_inputs(attempt_dir)
    if inputs is None:
        raise RenderUnavailable(
            "This cut was made before a cut kept its render inputs. Cut again to render it."
        )
    date_range = _date_range(run)
    params = _params(config, client, run, inputs.binding["policy"])
    params.editorial_attempt_dir = attempt_dir
    params.progress_callback = progress_callback
    params.phase_callback = phase_callback
    _apply_request(
        params, request, run, date_range, list(inputs.clips), read_cut_titles(attempt_dir)
    )
    projection = project_revision(
        attempt_dir,
        revision,
        _fetcher(client),
        timing_policy_for_params(params),
        live_motion=_live_motion(config, client),
    )
    # The owner's edits may have made the film longer; the render asks for the length they need.
    params.target_duration_seconds = projection.binding["policy"]["target_seconds"]
    params.clips = list(projection.clips)
    params.editorial_selections = projection.selections
    params.clip_segments = projection.segments
    params.timeline_plan = projection.timeline
    params.editorial_render_timing = projection.binding
    if request.output_orientation in {None, "auto"}:
        params.output_canvas = resolve_output_canvas(
            resolution=request.output_resolution,
            orientation=request.output_orientation,
            configured_resolution=config.output.resolution_tuple,
            clips=params.clips,
        )
    params.output_path = name_after_recipe(
        build_memory_output_path(
            output_dir=config.output.output_path,
            person_names=list(run.memory_people),
            memory_type=run.memory_type,
            date_range=date_range,
            container=resolve_output_selection(
                config_codec=config.output.codec,
                config_container=config.output.format,
                format_override=request.output_format,
            ).container,
        ),
        selected_clips=params.clips,
        clip_segments=params.clip_segments,
        editorial_selections=params.editorial_selections,
        memory_type=run.memory_type,
        date_range=date_range,
        target_duration=projection.timeline.target_duration,
    )
    if projection.record is not None:
        from immich_memories.db import open_store
        from immich_memories.store.owner_edits import keep_owner_edits

        # `runs why` finds a revision's edits by the attempt they were made to (#871).
        params.editorial_owner_edits = {**projection.record, "edit_id": uuid4().hex}
        keep_owner_edits(
            open_store(config),
            params.editorial_owner_edits,
            film=params.output_path,
            attempt=attempt_dir,
        )
    return generate_memory(params)
