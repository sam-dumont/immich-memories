"""Prepare and assemble a base film on the current machine."""

from __future__ import annotations

import inspect
import shutil
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TypeVar, cast

from immich_memories.filename_builder import normalize_output_path
from immich_memories.generate_clips import (
    cleanup_temp_clips,
    extract_clips,
    keep_temp_clips,
    new_run_scratch,
)
from immich_memories.generate_privacy import (
    anonymize_clips_for_privacy,
    anonymize_preset_params,
    fake_names,
    preset_person_names,
    swap_names,
)
from immich_memories.generate_progress import (
    OperationalProgress,
    PipelineProgress,
    clip_preparation_events,
    render_progress_events,
)
from immich_memories.generate_settings import (
    announce_title_source,
    build_assembly_settings,
    create_assembler,
)
from immich_memories.generate_timeline import (
    apply_final_content_budget as _apply_final_content_budget,
)
from immich_memories.generate_timeline import (
    check_rendered_film,
    validate_certified_content,
)
from immich_memories.operations.phases import OperationalPhase
from immich_memories.processing.clip_validation import validate_clips
from immich_memories.processing.probe_cache import ProbeCache
from immich_memories.tracking.timed import timed
from immich_memories.tracking.timing import span

if TYPE_CHECKING:
    from immich_memories.cache.prepared_source_bank import PreparedSourceBank
    from immich_memories.config.loader import Config
    from immich_memories.generate import GenerationParams, PreparedGeneration
    from immich_memories.tracking import RunTracker

import logging

logger = logging.getLogger(__name__)
_CallResult = TypeVar("_CallResult")


def _build_download_coordinator(
    params: GenerationParams,
    cache_batch,
    output_dir: Path,
):
    """Build isolated download workers without sharing the generation client."""
    if params.client is None:
        return None

    from immich_memories.generate_downloads import fetch_temporary_asset
    from immich_memories.processing.download_coordinator import (
        DownloadCoordinator,
        build_sync_client_factory,
        has_sync_client_connection,
    )

    if not has_sync_client_connection(params.client):
        logger.debug("Download prefetch disabled: client cannot seed isolated workers")
        return None

    download_operation = None
    if cache_batch is None:

        def download_temporary_asset(client, asset):
            return fetch_temporary_asset(client, asset, output_dir)

        download_operation = download_temporary_asset
    return DownloadCoordinator(
        build_sync_client_factory(params.client, params.config.immich.api_version),
        cache_batch,
        params.config.analysis.download_workers,
        download_operation=download_operation,
    )


def _call_with_optional_probe_cache(
    callable_under_test: Callable[..., _CallResult],
    *args: object,
    probe_cache: ProbeCache,
    optional: Mapping[str, object] | None = None,
    **kwargs: object,
) -> _CallResult:
    """Pass run-scoped probing (and any ``optional`` keyword) only to callables that accept it."""
    signature_target = getattr(callable_under_test, "side_effect", None)
    if not callable(signature_target):
        signature_target = callable_under_test
    parameters: Iterable[inspect.Parameter]
    try:
        parameters = inspect.signature(signature_target).parameters.values()
    except (TypeError, ValueError):
        parameters = ()
    parameters = tuple(parameters)
    takes_any = any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters)
    names = {parameter.name for parameter in parameters}
    for name, value in {"probe_cache": probe_cache, **(optional or {})}.items():
        if takes_any or name in names:
            kwargs[name] = value
    return callable_under_test(*args, **kwargs)


def _build_settings_with_optional_probe_cache(
    params: GenerationParams,
    assembly_clips: list,
    *,
    probe_cache: ProbeCache,
):
    return _call_with_optional_probe_cache(
        build_assembly_settings,
        params,
        assembly_clips,
        probe_cache=probe_cache,
    )


def _create_assembler_with_optional_probe_cache(
    settings,
    config: Config,
    *,
    probe_cache: ProbeCache,
):
    return _call_with_optional_probe_cache(
        create_assembler,
        settings,
        config,
        probe_cache=probe_cache,
    )


def _extract_clips_with_optional_prefetch(
    params: GenerationParams,
    cache_batch,
    output_dir: Path,
    *,
    probe_cache: ProbeCache,
    prepared_sources: PreparedSourceBank | None = None,
    scratch_dir: Path | None = None,
) -> list:
    """Keep the legacy extraction call shape when prefetch is unavailable."""
    coordinator = _build_download_coordinator(params, cache_batch, output_dir)
    reuse = {"prepared_sources": prepared_sources, "scratch_dir": scratch_dir}
    if coordinator is None:
        return _call_with_optional_probe_cache(
            extract_clips,
            params,
            cache_batch,
            output_dir,
            probe_cache=probe_cache,
            optional=reuse,
        )
    return _call_with_optional_probe_cache(
        extract_clips,
        params,
        cache_batch,
        output_dir,
        download_coordinator=coordinator,
        probe_cache=probe_cache,
        optional=reuse,
    )


def _prepared_source_bank(config: Config) -> PreparedSourceBank | None:
    """The bank of earlier runs' prepared sources, when caching is on (#2032).

    It follows `cache.video_cache_enabled`: someone who keeps no downloaded videos
    on disk gets no prepared ones either.
    """
    from immich_memories.cache.prepared_source_bank import PreparedSourceBank

    budget_gb = config.analysis.prepared_source_cache_max_size_gb
    if not config.cache.video_cache_enabled or budget_gb <= 0:
        return None
    try:
        bank = PreparedSourceBank(
            config.cache.cache_path / "prepared-sources",
            max_bytes=int(budget_gb * 1_073_741_824),
        )
        bank.begin_run()
    except OSError as exc:
        logger.warning("Prepared sources will not be reused this run: %s", exc)
        return None
    return bank


def _close_prepared_source_bank(bank: PreparedSourceBank | None, sources: int) -> None:
    if bank is None:
        return
    logger.info(
        "Prepared sources: %d reused from earlier runs, %d newly banked, of %d",
        bank.taken,
        bank.kept,
        sources,
    )
    try:
        bank.enforce_budget()
    except OSError:
        logger.debug("Prepared-source eviction failed", exc_info=True)


def _emit_download_phase(
    operational: OperationalProgress,
    params: GenerationParams,
    current: int,
    total: int,
    message: str,
) -> None:
    """Report direct-generation download work only while this call owns it."""
    if operational.phase_is_unperformed(OperationalPhase.DOWNLOAD):
        operational.emit(OperationalPhase.DOWNLOAD, current, total, message)


def _with_clip_preparation_events(
    params: GenerationParams, operational: OperationalProgress
) -> GenerationParams:
    """Report "Preparing clips (n/N)" while sources download and cut (#2243)."""
    total = len(params.clips)
    if operational.phase_is_unperformed(OperationalPhase.DOWNLOAD):
        phase = OperationalPhase.DOWNLOAD
    else:
        # Selection already finished upstream: the next phase the lifecycle allows is render.
        phase = OperationalPhase.RENDER
        operational.emit(phase, 0, total, f"Preparing clips (0/{total})")
    callback = clip_preparation_events(params.progress_callback, operational, phase, total)
    return replace(params, progress_callback=callback)


def _extracted_sources(
    params: GenerationParams,
    run_output_dir: Path,
    *,
    probe_cache: ProbeCache,
    scratch_dir: Path | None = None,
) -> list:
    """Own the persistent video-cache lifecycle across exactly one extraction."""
    from immich_memories.cache.video_cache import VideoDownloadCache

    if not params.config.cache.video_cache_enabled:
        # Disabled cache means no interaction with the configured persistent
        # video cache. Extraction uses disposable run-local downloads.
        return _extract_clips_with_optional_prefetch(
            params, None, run_output_dir, probe_cache=probe_cache, scratch_dir=scratch_dir
        )
    video_cache = VideoDownloadCache(
        cache_dir=params.config.cache.video_cache_path,
        max_size_gb=params.config.cache.video_cache_max_size_gb,
        max_age_days=params.config.cache.video_cache_max_age_days,
    )
    bank = _prepared_source_bank(params.config)
    # One cache lifecycle owns all persistent-cache downloads for this
    # generation. It scans once, then evicts from the manifest on exit.
    try:
        with video_cache.begin_batch() as cache_batch:
            return _extract_clips_with_optional_prefetch(
                params,
                cache_batch,
                run_output_dir,
                probe_cache=probe_cache,
                prepared_sources=bank,
                scratch_dir=scratch_dir,
            )
    finally:
        _close_prepared_source_bank(bank, len(params.clips))


def anonymized_params(params: GenerationParams) -> GenerationParams:
    # One mapping for the selected person and the preset's cast, so a film names each
    # person by the same fake wherever the name shows.
    fakes = fake_names([params.person_name, *preset_person_names(params.memory_preset_params)])
    return replace(
        params,
        person_name=fakes.get(params.person_name) if params.person_name else None,
        title=swap_names(params.title, fakes),
        subtitle=swap_names(params.subtitle, fakes),
        memory_preset_params=anonymize_preset_params(params.memory_preset_params, fakes),
    )


@timed("render")
def render_base(params, output_path, directory, tracker, operational, progress, phase_times):
    """Choose the configured renderer and keep one progress and run-tracking lifecycle."""
    from immich_memories.generate import GenerationError
    from immich_memories.processing.remote_render import RemoteRenderClient

    if params.config.render.enabled:
        operational.emit_unperformed_prerequisites(OperationalPhase.SELECTION)
        operational.emit(OperationalPhase.RENDER, 0, len(params.clips), "Rendering on worker")
        tracker.start_phase("assembly", len(params.clips))
        try:
            with (
                span("render.assembly", items=len(params.clips)) as remote,
                RemoteRenderClient(params.config.render) as worker,
            ):
                result = worker.render(params, output_path.with_suffix(".mp4"), progress.report)
        except GenerationError:
            if not params.config.render.fallback_to_local:
                raise
            logger.warning("Render worker failed; rendering the same selected cut locally")
            tracker.complete_phase(items_processed=0, errors=[{"error": "Worker render failed"}])
        else:
            tracker.complete_phase(
                items_processed=result.clips_selected, extra_metrics=result.render_metrics
            )
            operational.emit(
                OperationalPhase.RENDER,
                result.clips_selected,
                result.clips_selected,
                "Render complete",
            )
            phase_times["assembly"] = remote.duration
            return result
    return render_local(params, output_path, directory, tracker, operational, progress, phase_times)


def render_local(
    params: GenerationParams,
    requested_output_path: Path,
    run_output_dir: Path,
    run_tracker: RunTracker,
    operational: OperationalProgress,
    pp: PipelineProgress,
    phase_times: dict[str, float],
) -> PreparedGeneration:
    """Own source preparation and assembly; return metadata for the common music phase."""
    from immich_memories.generate import GenerationError, PreparedGeneration

    probe_cache = ProbeCache()
    run_scratch = new_run_scratch()
    assembly_clips: list = []
    try:
        with span("render.clip_extraction", items=len(params.clips)) as extraction:
            # Phase 1: Download and extract clips
            pp.report("download", 0.0, "Preparing clips...")
            run_tracker.start_phase("clip_extraction", len(params.clips))
            _emit_download_phase(
                operational,
                params,
                0,
                len(params.clips),
                "Preparing clips",
            )

            assembly_clips = _extracted_sources(
                _with_clip_preparation_events(params, operational),
                run_output_dir,
                probe_cache=probe_cache,
                scratch_dir=run_scratch,
            )
            run_tracker.complete_phase(items_processed=len(assembly_clips))
            _emit_download_phase(
                operational,
                params,
                len(assembly_clips),
                len(params.clips),
                "Sources prepared",
            )
            operational.emit_unperformed_prerequisites(OperationalPhase.SELECTION)
            operational.emit(OperationalPhase.RENDER, 0, len(params.clips), "Rendering memory")
        phase_times["prepare"] = extraction.duration
        pp.report("download", 1.0, "Clips prepared")

        # Pre-assembly validation: skip clips with missing/empty files
        assembly_clips, skipped = validate_clips(assembly_clips)
        validate_certified_content(params, assembly_clips)
        _refuse_vanished_clips(skipped)

        if not assembly_clips:
            raise GenerationError("No clips could be processed")

        # Privacy mode: anonymize GPS + names before title/assembly
        if params.privacy_mode:
            assembly_clips = anonymize_clips_for_privacy(assembly_clips)
            params = anonymized_params(params)

        assembly_clips = _apply_final_content_budget(params, assembly_clips)
        validate_certified_content(params, assembly_clips)

        from immich_memories.generate_captions import (
            locality_place_names,
            prepare_location_captions,
        )

        assembly_clips = locality_place_names(params, assembly_clips)

        # Phase 2: Assemble (includes title generation + streaming encode)
        with span("render.assembly", items=len(assembly_clips)) as assembly:
            assembly_cb = render_progress_events(
                pp.assembly_callback(), operational, len(assembly_clips)
            )
            run_tracker.start_phase("assembly", len(assembly_clips))

            settings = _build_settings_with_optional_probe_cache(
                params,
                assembly_clips,
                probe_cache=probe_cache,
            )
            assembly_clips = prepare_location_captions(
                params, assembly_clips, title_settings=settings.title_screens
            )
            if settings.title_screens is not None:
                announce_title_source(settings.title_screens, run_tracker)
            result_output_path = normalize_output_path(
                requested_output_path,
                cast(Literal["mp4", "mov"], settings.encoding_plan.container),
            )
            assembler = _create_assembler_with_optional_probe_cache(
                settings,
                params.config,
                probe_cache=probe_cache,
            )
            staged_output_path = result_output_path.with_name(
                f"{result_output_path.stem}.assembling{result_output_path.suffix}"
            )
            with span("render.encode", items=len(assembly_clips)) as encode:
                staged_result_path = assembler.assemble_with_titles(
                    assembly_clips,
                    staged_output_path,
                    assembly_cb,
                    frame_preview_callback=params.frame_preview_callback,
                )
            # Titles included: every second of it was this machine producing the
            # film, and decoding the result can only be faster.
            encode_seconds = encode.duration
            plan = settings.encoding_plan
            film_timeline = settings.film_timeline
            if film_timeline is not None:
                run_tracker.record_film_timeline(film_timeline)
            metrics, duration_warning = check_rendered_film(
                params,
                staged_result_path,
                plan,
                film_timeline.map_extra_seconds if film_timeline is not None else 0.0,
            )
            run_tracker.complete_phase(items_processed=len(assembly_clips), extra_metrics=metrics)
            operational.emit(
                OperationalPhase.RENDER,
                len(assembly_clips),
                len(assembly_clips),
                "Render complete",
            )
        phase_times["assembly"] = assembly.duration
        return PreparedGeneration(
            path=result_output_path,
            staged_path=staged_result_path,
            encoding_plan=plan,
            assembly_clips=tuple(assembly_clips),
            clips_analyzed=len(params.clips),
            clips_selected=len(assembly_clips),
            music_mute_windows=settings.music_mute_windows,
            duration_warning=duration_warning,
            render_metrics=metrics,
            encode_seconds=encode_seconds,
        )
    finally:
        _release_cut_segments(params, assembly_clips, run_output_dir, run_scratch)


def _refuse_vanished_clips(skipped: list) -> None:
    """A prepared shot whose file is gone stops the film instead of shortening it.

    Preparation already let every source it could not render leave the film by name.
    A file that existed when it was prepared and is missing or empty now was removed
    by something else, and the film would come out short without saying why (#2452).
    """
    from immich_memories.generate import GenerationError

    if skipped:
        named = ", ".join(clip.asset_id or clip.path.name for clip in skipped)
        raise GenerationError(
            f"A prepared clip disappeared before assembly ({named}); render the film again"
        )


def _release_cut_segments(
    params: GenerationParams, assembly_clips: list, run_output_dir: Path, run_scratch: Path
) -> None:
    """Delete the cut segments, or keep them beside the film for --keep-intermediates.

    WHY (#2346): this runs before the run closes, so deleting the segments here
    unconditionally left --keep-intermediates nothing to keep.
    """
    try:
        if params.debug_preserve_intermediates:
            keep_temp_clips(assembly_clips, run_output_dir / ".intermediates")
        else:
            cleanup_temp_clips(assembly_clips)
    except OSError:
        logger.debug("Temp clip cleanup failed", exc_info=True)
    # Whatever else the run cut and never used goes with it; no other run reads here.
    shutil.rmtree(run_scratch, ignore_errors=True)
