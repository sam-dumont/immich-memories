"""Which model producer still owes a fact, and who is allowed to answer for it.

Five decisions live here, in this order: which stills an earlier exposure answer still
covers, what the inference service may be asked for, which pictures the packaged public
heads still owe, which sources the detector worker must read, and which attached clips
owe the exposure head a row of their own. A head nothing packages is named rather than
silently skipped.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Protocol

from immich_memories.analysis.editorial_clip_frames import CLIP_FRAMES_HEAD, CLIP_FRAMES_VERSION
from immich_memories.analysis.editorial_obstruction import HEAD_NAME as OBSTRUCTION_HEAD
from immich_memories.analysis.editorial_obstruction import HEAD_VERSION as OBSTRUCTION_VERSION
from immich_memories.analysis.editorial_preparation_detector_frames import (
    DetectorFrames,
    served_locally,
)
from immich_memories.analysis.editorial_preparation_detectors import (
    DETECTOR_VERSIONS,
    MARQO_HEAD,
    MARQO_ONNX_ID,
    MARQO_STILL_EQUIVALENT,
)
from immich_memories.analysis.editorial_preparation_heads import PUBLIC_HEAD_VERSIONS
from immich_memories.analysis.editorial_preparation_remote_frames import prepare_remote_frame_facts
from immich_memories.analysis.remote_facts import RemoteFactsError, offloaded_versions
from immich_memories.api.models import Asset
from immich_memories.config_models_editorial_preparation import EditorialPreparationConfig
from immich_memories.config_models_inference import InferenceConfig
from immich_memories.db import Store
from immich_memories.store.editorial_preparation import carry_head_answers, heads_missing_for


class ModelFactStage(Protocol):
    """The preparation seams this plan drives; `_Acquisition` satisfies it structurally."""

    @property
    def failures(self) -> dict[str, str]: ...

    @property
    def service_seconds(self) -> dict[str, float]: ...

    @property
    def store(self) -> Store: ...

    @property
    def inference_config(self) -> InferenceConfig: ...

    @property
    def preparation_config(self) -> EditorialPreparationConfig: ...

    @property
    def check(self) -> Callable[[], None]: ...

    @property
    def report(self) -> Callable[[str, int, int], None]: ...

    def timed(self, stage: str, pictures: int) -> AbstractContextManager[None]: ...

    def scoped(self, scope: str) -> ModelFactStage: ...

    def public_heads(self, asset_ids: Sequence[str], head_versions: Mapping[str, str]) -> None: ...

    def obstruction_heads(self, asset_ids: Sequence[str]) -> None: ...

    def detectors(
        self,
        pending: Mapping[str, Sequence[str]],
        preview_paths: Mapping[str, Path],
        frame_paths: Mapping[str, Sequence[Path]],
    ) -> None: ...

    def remote_facts(self, pending: Mapping[str, Mapping[str, str]]) -> bool: ...

    def clip_frames(self, frame_paths: Mapping[str, Sequence[Path]]) -> None: ...

    def video_motion(
        self, frame_paths: Mapping[str, Sequence[Path]], videos: Mapping[str, Asset]
    ) -> None: ...

    def obstruction_frames(
        self, frame_paths: Mapping[str, Sequence[Path]], videos: Mapping[str, Asset]
    ) -> None: ...

    def previews(
        self,
        ids: Sequence[str],
        cache_path: Path,
        fetch_preview: Any,
        edited_by_id: Mapping[str, bool] | None = None,
    ) -> tuple[dict[str, Path], list[str]]: ...

    @property
    def unservable(self) -> dict[str, str]: ...


CLIP_COMPANION = "clip_companion"


def carry_still_exposure(
    store: Store, source: Sequence[Asset], head_versions: Mapping[str, str]
) -> None:
    """Bank a still's earlier exposure answer as the current one instead of reading it again.

    The current version changed how a video is read and nothing about a still, which is
    still decided on its preview by the same export. A video, and a Live Photo's clip
    (never in ``source``), keep owing the current version a read of their own.
    """
    version = head_versions.get(MARQO_HEAD, "")
    if version != DETECTOR_VERSIONS[MARQO_HEAD]:
        return
    carry_head_answers(
        store,
        [asset.id for asset in source if not asset.is_video],
        MARQO_HEAD,
        banked_version=MARQO_STILL_EQUIVALENT,
        version=version,
        encoder_key=MARQO_ONNX_ID,
    )


def deferred_exposure(
    missing: Mapping[str, tuple[str, ...]], source: Sequence[Asset]
) -> dict[str, tuple[str, ...]]:
    """Defer video exposure entirely; a preview must not earn the sampled-frame version.

    The selected-candidate pass will owe this producer's actual frame inspection. Other
    cheap heads can still read a video's preview while the NAS draft is being built.
    """
    key = f"head:{MARQO_HEAD}@{DETECTOR_VERSIONS[MARQO_HEAD]}"
    videos = {asset.id for asset in source if asset.is_video}
    result = dict(missing)
    if key in result:
        result[key] = tuple(asset for asset in result[key] if asset not in videos)
        if not result[key]:
            del result[key]
    return result


def acquire_clip_companions(
    stage: ModelFactStage,
    frames: DetectorFrames,
    cache_path: Path,
    fetch_preview: Any,
    head_versions: Mapping[str, str],
) -> None:
    """Read a Live Photo's clip the way any clip is read; its still never stood for it.

    Bounded on purpose: the exposure head only, over the attached clips of the Live Photos
    in scope. No caption, no context head, no pixel fact -- a clip is not a candidate, it
    is material a unit can play, and the audience gate is the only pass that asks about it.
    Nothing here can block a cut either: a clip Immich will not serve leaves its still in
    the film and one named failure behind, because a missing clip row is exactly the
    evidence every Live Photo had before this existed.
    """
    version = head_versions.get(MARQO_HEAD, "")
    if not frames.companion_ids or DETECTOR_VERSIONS.get(MARQO_HEAD) != version:
        return
    owed = heads_missing_for(stage.store, sorted(frames.companion_ids), MARQO_HEAD, version)
    if not owed:
        return
    stage = stage.scoped("live_photos")
    refused = set(stage.unservable)
    paths, _unusable = stage.previews(owed, cache_path, fetch_preview)
    # A clip Immich will not preview is not a source leaving the film: its still stays.
    # Nor is it unread: Immich keeps no preview for many Live Photo clips and plays them all.
    no_preview = {
        asset_id: stage.unservable.pop(asset_id) for asset_id in set(stage.unservable) - refused
    }
    for batch, offset, total in frames.batches(owed, stage.preparation_config.batch_size):
        with frames.sampled(
            batch,
            check=stage.check,
            report=stage.report,
            failures=stage.failures,
            timed=stage.timed,
            offset=offset,
            total=total,
        ) as sampled:
            for asset_id in batch:
                if asset_id in no_preview and asset_id not in sampled:
                    stage.failures[f"{CLIP_COMPANION}:{asset_id}"] = no_preview[asset_id]
            readable = tuple(key for key in batch if key in paths or key in sampled)
            if readable:
                _sampled_models(stage, {MARQO_HEAD: readable}, paths, sampled, {})


def acquire_model_facts(
    stage: ModelFactStage,
    before: Mapping[str, Sequence[str]],
    ids: Sequence[str],
    available: set[str],
    pending: Callable[[str], tuple[str, ...]],
    head_versions: Mapping[str, str],
    preview_paths: Mapping[str, Path],
    frames: DetectorFrames,
    clips: Sequence[str] = (),
    motion: Mapping[str, Asset] | None = None,
) -> None:
    """``clips`` are the videos that owe their frame reading and ``motion`` the ones that owe a
    measured residual; they share the exposure head's sampled frames, so a clip is read off
    Immich once for all three."""
    motion = motion or {}
    head_versions, offloaded_exposure = _after_remote(
        stage, before, ids, available, head_versions, frames.video_ids
    )
    requested_public = {
        head: version for head, version in head_versions.items() if head in PUBLIC_HEAD_VERSIONS
    }
    public_ids = _public_head_ids(before, ids, available, requested_public)
    if public_ids:
        stage.public_heads(public_ids, requested_public)
    # #2022: its own path, not the required public heads' bundle, so it is asked for by
    # name rather than through `before` (which only ever scans the configured heads).
    obstruction_ids = heads_missing_for(
        stage.store, [a for a in ids if a in available], OBSTRUCTION_HEAD, OBSTRUCTION_VERSION
    )
    if obstruction_ids:
        stage.obstruction_heads(obstruction_ids)
    detector_pending = _detector_pending(pending, head_versions, offloaded_exposure)
    _acquire_frame_batches(stage, detector_pending, preview_paths, frames, clips, motion)
    _record_unpackaged_heads(pending, head_versions, stage.failures)


def _acquire_frame_batches(stage, pending, previews, frames, clips, motion):
    exposure = [key for key in pending.get(MARQO_HEAD, ()) if key in frames.clip_ids]
    ids = tuple(dict.fromkeys((*exposure, *clips, *motion)))
    wanted = set(ids)
    # Stills need no temporary frames. Keep their model pass together so a local
    # detector process is not reloaded once per small disk working set.
    stills = {
        head: tuple(key for key in keys if key not in wanted) for head, keys in pending.items()
    }
    _sampled_models(stage, stills, previews, {}, {})
    stage = stage.scoped("videos")
    for batch, offset, total in frames.batches(ids, stage.preparation_config.batch_size):
        batch_ids = set(batch)
        batch_pending = {
            head: tuple(key for key in keys if key in batch_ids) for head, keys in pending.items()
        }
        with frames.sampled(
            batch,
            check=stage.check,
            report=stage.report,
            failures=stage.failures,
            timed=stage.timed,
            offset=offset,
            total=total,
        ) as sampled:
            owed = {clip: sampled[clip] for clip in clips if clip in sampled}
            _sampled_models(stage, batch_pending, previews, sampled, owed)
            if measurable := {video: sampled[video] for video in motion if video in sampled}:
                stage.video_motion(measurable, motion)
                stage.obstruction_frames(measurable, motion)


def _sampled_models(stage, pending, previews, frames, clips) -> None:
    if stage.inference_config.enabled:
        pending, clips = _offload_sampled(stage, pending, previews, frames, clips)
    if local := {head: ids for head, ids in pending.items() if ids}:
        stage.detectors(local, previews, frames)
    if clips:
        stage.clip_frames(clips)


def _offload_sampled(stage, pending, previews, frames, clips):
    config = stage.inference_config
    exposure = pending.get(MARQO_HEAD, ()) if MARQO_HEAD in config.producers else ()
    remote_clips = clips if "heads" in config.producers else {}
    if not exposure and not remote_clips:
        return pending, clips
    _read_remote_samples(stage, exposure, remote_clips, previews, frames)
    pending = dict(pending)
    if exposure:
        pending[MARQO_HEAD] = (
            heads_missing_for(stage.store, exposure, MARQO_HEAD, DETECTOR_VERSIONS[MARQO_HEAD])
            if config.fallback_to_local
            else ()
        )
    if remote_clips:
        missing = (
            heads_missing_for(
                stage.store, list(remote_clips), CLIP_FRAMES_HEAD, CLIP_FRAMES_VERSION
            )
            if config.fallback_to_local
            else ()
        )
        clips = {asset_id: clips[asset_id] for asset_id in missing}
    return pending, clips


def _read_remote_samples(stage, exposure, clips, previews, frames) -> None:
    config = stage.inference_config
    try:
        with stage.timed("remote_frames", len(set(exposure) | set(clips))):
            charged = prepare_remote_frame_facts(
                exposure=exposure,
                clips=clips,
                frame_paths=frames,
                preview_paths=previews,
                store=stage.store,
                config=config,
                check=stage.check,
                progress=stage.report,
            )
        if charged is not None:
            stage.service_seconds["remote_frames"] = (
                stage.service_seconds.get("remote_frames", 0) + charged
            )
    except (RemoteFactsError, OSError) as exc:
        outcome = "local producers took over" if config.fallback_to_local else "no local fallback"
        key = "remote_frames" if exposure else CLIP_FRAMES_HEAD
        stage.failures[key] = f"inference service at {config.facts_base_url}: {exc}; {outcome}"


def _after_remote(
    stage: ModelFactStage,
    before: Mapping[str, Sequence[str]],
    ids: Sequence[str],
    available: set[str],
    head_versions: Mapping[str, str],
    videos: frozenset[str],
) -> tuple[Mapping[str, str], frozenset[str]]:
    """Offload what the service answers for.

    Returns the head versions the local producers still owe, and the sources whose
    exposure head the service did answer for -- a head that stays local for the videos
    alone must not be paid for again on every still.
    """
    if not stage.inference_config.enabled:
        return head_versions, frozenset()
    offloaded = offloaded_versions(head_versions, stage.inference_config.producers)
    pending, withheld = _offload_requests(before, ids, available, offloaded, videos)
    served = stage.remote_facts(pending)
    if not served and stage.inference_config.fallback_to_local:
        return head_versions, frozenset()
    # A head the service was not allowed to answer for on every source is still owed in
    # process, whatever the service did with the sources it was given.
    answered = {head for head in offloaded if not (withheld and head == MARQO_HEAD)}
    exposure = (
        frozenset(a for a, heads in pending.items() if MARQO_HEAD in heads)
        if served
        else frozenset()
    )
    return {h: v for h, v in head_versions.items() if h not in answered}, exposure


def _offload_requests(
    before: Mapping[str, Sequence[str]],
    ids: Sequence[str],
    available: set[str],
    offloaded: Mapping[str, str],
    videos: frozenset[str],
) -> tuple[dict[str, dict[str, str]], bool]:
    """What each source still owes that the service may answer, and whether any was withheld."""
    missing = {
        head: set(before.get(f"head:{head}@{version}", ())) for head, version in offloaded.items()
    }
    pending: dict[str, dict[str, str]] = {}
    withheld = False
    for asset_id in (asset_id for asset_id in ids if asset_id in available):
        local = served_locally(offloaded, asset_id, videos)
        withheld = withheld or local
        wanted = {
            head: version
            for head, version in offloaded.items()
            if asset_id in missing[head] and not (local and head == MARQO_HEAD)
        }
        if wanted:
            pending[asset_id] = wanted
    return pending, withheld


def _public_head_ids(
    before: Mapping[str, Sequence[str]],
    ids: Sequence[str],
    available: set[str],
    requested_public: Mapping[str, str],
) -> tuple[str, ...]:
    missing_public = set().union(
        *(
            set(before.get(f"head:{head}@{version}", ()))
            for head, version in requested_public.items()
        )
    )
    return tuple(
        asset_id for asset_id in ids if asset_id in available and asset_id in missing_public
    )


def _detector_pending(
    pending: Callable[[str], tuple[str, ...]],
    head_versions: Mapping[str, str],
    offloaded_exposure: frozenset[str],
) -> dict[str, tuple[str, ...]]:
    demanded = {
        head: tuple(
            asset_id
            for asset_id in pending(f"head:{head}@{version}")
            if head != MARQO_HEAD or asset_id not in offloaded_exposure
        )
        for head, version in head_versions.items()
        if DETECTOR_VERSIONS.get(head) == version
    }
    return {head: values for head, values in demanded.items() if values}


def _record_unpackaged_heads(
    pending: Callable[[str], tuple[str, ...]],
    head_versions: Mapping[str, str],
    failures: dict[str, str],
) -> None:
    supported = PUBLIC_HEAD_VERSIONS | DETECTOR_VERSIONS
    for head, version in head_versions.items():
        if pending(f"head:{head}@{version}") and supported.get(head) != version:
            failures[f"head_provider:{head}"] = f"no packaged producer for {head}@{version}"
