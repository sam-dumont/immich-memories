"""Replaceable production edges for the store-backed editorial planner."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from immich_memories.analysis.catalogue_runtime import catalogue_requester
from immich_memories.analysis.editorial_preparation_motion import BankedMotionLines, motion_producer
from immich_memories.analysis.editorial_source import (
    FullEditorialSource,
    fetch_full_window_source,
)
from immich_memories.analysis.editorial_structure_contract import (
    StructurePlannerPorts,
    StructurePlanningInput,
    StructurePlanningResult,
)
from immich_memories.analysis.editorial_structure_planner import plan_structure
from immich_memories.analysis.editorial_text_gateway import SyncTextPromptRequester
from immich_memories.analysis.llm_batch import BatchCoordinator, BatchPolicy
from immich_memories.analysis.selection_source import SourceScope
from immich_memories.analysis.subject_framing import FaceBox, face_boxes_of
from immich_memories.analysis.text_episode_paging import TEXT_EPISODE_MAX_OUTPUT_TOKENS
from immich_memories.api.models import Asset, VideoClipInfo
from immich_memories.people.context import PersonPromptContext, load_people_prompt_context
from immich_memories.store.episode_readings import EpisodeReadingStore

if TYPE_CHECKING:
    from immich_memories.config_loader import Config
    from immich_memories.db import Store


def _load_people() -> Mapping[str, PersonPromptContext]:
    return load_people_prompt_context(include_derived=True)


@dataclass(frozen=True, slots=True)
class EditorialRuntimePorts:
    """Explicit replaceable edges around production I/O, suitable for public tests."""

    load_people: Callable[[], Mapping[str, PersonPromptContext]] = _load_people
    fetch_preview: Callable[[Any, str], bytes | None] = lambda client, asset_id: (
        client.get_asset_thumbnail(asset_id, size="preview")
    )
    # Immich names the people it recognised on the asset itself but hands back no
    # geometry there; where each face sits has its own endpoint.
    fetch_faces: Callable[[Any, str], Sequence[FaceBox]] = lambda client, asset_id: face_boxes_of(
        client.get_asset_faces(asset_id)
    )
    fetch_playback_range: Callable[[Any, str, int, int], tuple[bytes, int]] = (
        lambda client, asset_id, start, length: client.get_video_playback_range(
            asset_id, start, length
        )
    )
    fetch_full_source: Callable[
        [FullEditorialSource, SourceScope], Sequence[Asset | VideoClipInfo]
    ] = fetch_full_window_source
    # The episode reads are the one stage with a fan-out worth queueing, so the
    # batch coordinator is built here and nowhere else. Story picks depend on
    # the stages before them.
    episode_requester_factory: Callable[[Config], Callable[[str], str]] = lambda config: (
        SyncTextPromptRequester(
            config.llm,
            max_tokens=TEXT_EPISODE_MAX_OUTPUT_TOKENS,
            timeout_seconds=config.llm.timeout_seconds,
            thinking=False,
            batch=BatchCoordinator(config.llm, BatchPolicy.from_config(config.llm)),
        )
    )
    # The period account is one small request over readings the run has already paid for,
    # so it uses its own plain transport rather than the episode batch above.
    catalogue_requester_factory: Callable[[Config], Callable[[str], str]] = catalogue_requester
    episode_store_factory: Callable[[Store], EpisodeReadingStore] = EpisodeReadingStore
    structure_planner: Callable[
        [StructurePlanningInput, StructurePlannerPorts], StructurePlanningResult
    ] = plan_structure
    structure_ports_factory: Callable[[StructurePlanningInput], StructurePlannerPorts] | None = None
    prepare_annotations: Callable[..., Any] | None = None


def production_story_motion(source, *, store):
    """The pick's motion evidence, read from the preparation bank; no model call, no download."""
    return BankedMotionLines(
        store=store,
        assets=source.assets,
        described=source.config.editorial.preparation.demands_captions,
        producer=motion_producer(source.config.editorial.description_model),
    )


def _stage_reads(source):
    """One stage's client, reading each of its pictures and companions through its account."""
    from immich_memories.api.access_clients import reads_for

    return reads_for(
        source.config.immich, [*source.assets.values(), *source.companion_assets.values()]
    )


def production_live_clock_offsets(source, *, resources):
    """Measure Live companion clock offsets for content-aligned stitch joins (#1012).

    Asked only about the bursts a cut keeps, and banked per pair of companions, so a
    burst is downloaded once for every cut that ever keeps it. A pair the correlation
    refuses (a hard cut, exposure shift, or too little shared content) answers None,
    and the caller keeps the still for that burst.
    """
    from immich_memories.analysis.live_clock_offsets import BankedClockOffsets

    client = None

    def fetch(video_id: str) -> bytes:
        nonlocal client
        if client is None:
            client = _stage_reads(source)
            resources.callback(client.close)
        return client.get_video_playback(video_id)

    return BankedClockOffsets(store=source.store, companions=source.companion_assets, fetch=fetch)


# A clip whose own soundtrack is musical for a third of what this cut heard has a real
# music/singing presence (#466, #1951); a few seconds of background TV in a minute-long
# clip should not duck the added soundtrack for its whole window.
_HAS_MUSIC_SHARE = 0.3


def _tag_has_music(carriers, music_for: Callable[[str], float]) -> None:
    for carrier in carriers:
        if carrier["kind"] in {"video", "live-motion"}:
            carrier["has_music"] = music_for(carrier["asset_id"]) >= _HAS_MUSIC_SHARE


def production_cut_resolvers(source, *, resources):
    """Where each kept video plays, then where its cut may end, from one listening (#1949).

    The window step reads each kept video's index and the sound of one bounded span by byte
    range; the speech cut reuses what it heard. Only Live Photo clips, a few seconds each,
    are still fetched whole for their speech.
    """
    import json
    import logging

    from immich_memories.analysis.editorial_clip_facts import ClipWindowFacts
    from immich_memories.analysis.editorial_speech import resolve_speech_cuts, speech_buffer
    from immich_memories.analysis.editorial_video_windows import place_windows
    from immich_memories.speech.facts import SpeechFacts

    client = None

    def reads():
        nonlocal client
        if client is None:
            client = _stage_reads(source)
            resources.callback(client.close)
        return client

    def fetch(asset_id, path):
        # WHY: a whole video's rendition streams to disk; bytes would hold it in RAM
        reads().download_playback(asset_id, path)

    speech_config = source.config.speech
    speech = (
        SpeechFacts(
            assets=dict(source.assets) | dict(source.companion_assets),
            store=source.store,
            fetch=fetch,
            config=speech_config,
        )
        if speech_config.enabled
        else None
    )
    windows = ClipWindowFacts(
        assets=dict(source.assets),
        store=source.store,
        read=lambda asset_id, start, length: reads().get_video_playback_range(
            asset_id, start, length
        ),
        detector=speech.detector if speech is not None else None,
        detector_settings=json.dumps(speech_config.model_dump(), sort_keys=True),
    )

    def resolve_windows(carriers):
        try:
            return place_windows(carriers, windows)
        finally:
            windows.flush()

    if speech is None:
        return resolve_windows, None

    def regions_for(asset_id):
        heard = windows.speech_for(asset_id)
        return heard if heard is not None else speech(asset_id)

    def music_for(asset_id):
        fraction = windows.music_fraction_for(asset_id)
        return fraction if fraction is not None else speech.music_for(asset_id)

    def resolve_speech(carriers):
        if not any(c["kind"] in {"video", "live-motion"} for c in carriers):
            return carriers
        if not speech.detector.available:
            logging.getLogger(__name__).warning(
                "Speech boundary detection is unavailable; cuts may interrupt speech. "
                "Install immich-memories[editorial] to enable the local detector."
            )
            return carriers
        try:
            resolved = resolve_speech_cuts(
                carriers, regions_for, buffer=speech_buffer(source.config)
            )
            _tag_has_music(resolved, music_for)
            return resolved
        finally:
            speech.flush()

    return resolve_windows, resolve_speech
