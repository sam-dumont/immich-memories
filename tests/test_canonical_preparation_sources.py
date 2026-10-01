"""Canonical favourite promotion must not change the footage producers measured."""

from dataclasses import replace
from functools import partial

import pytest

from immich_memories.analysis.editorial_bound_sample import source_metadata_digest
from immich_memories.analysis.editorial_clip_frames import CLIP_FRAMES_HEAD, CLIP_FRAMES_VERSION
from immich_memories.analysis.editorial_preparation import prepare_editorial_annotations
from immich_memories.analysis.editorial_runtime_evidence import (
    AnnotationReadings,
    EvidencePreparation,
)
from immich_memories.analysis.editorial_runtime_ports import EditorialRuntimePorts
from immich_memories.analysis.editorial_video_motion import VIDEO_RESIDUAL_PRODUCER
from immich_memories.analysis.selection_source import (
    EditorialDependencies,
    EditorialSelectionRequest,
    SourceScope,
    prepare_editorial_source,
)
from immich_memories.api.models import AssetType
from immich_memories.config import Config
from immich_memories.store.cut_measurements import PendingMeasurements
from tests.annotation_rows import add_rows, annotation_store
from tests.conftest import make_asset
from tests.test_editorial_preparation import preview, successful_ports


def _cached_preparation(tmp_path):
    raw = make_asset("original", original_file_name="IMG_1234.MOV", duration="0:00:06.000")
    raw.type = AssetType.VIDEO
    raw.width, raw.height = 1920, 1080
    copy = raw.model_copy(
        update={"id": "album-copy", "width": 640, "height": 360, "is_favorite": True}
    )
    prepared = prepare_editorial_source(
        EditorialSelectionRequest(scope=SourceScope(min_source_short_side=0)),
        # WHY: generated Immich DTOs preserve the real picture-copy grouping path.
        EditorialDependencies(source_fetcher=lambda _scope: (raw, copy)),
    )
    assert prepared.candidate_ids == ("original",)
    assert prepared.candidates[0].favourite and prepared.candidates[0].source.is_favorite
    config = Config(tier="gpu")
    store = annotation_store()
    calls = []
    # WHY: external model ports seed their ordinary stored answers without loading models.
    providers = successful_ports(calls)
    kwargs = {
        "store": store,
        "thumbnail_cache": tmp_path / "previews",
        "preparation_config": config.editorial.preparation,
        "triage_config": config.triage,
        "head_versions": config.editorial.active_head_versions,
        "pixel_producer_key": config.editorial.pixel_producer_key,
        "ports": providers,
    }
    prepare_editorial_annotations(assets=[raw], fetch_preview=lambda _id: preview(), **kwargs)
    add_rows(
        store,
        "head_facts",
        {
            "asset_id": raw.id,
            "head": CLIP_FRAMES_HEAD,
            "version": CLIP_FRAMES_VERSION,
            "label": "shows-its-moment",
            "confidence": 1.0,
        },
    )
    with PendingMeasurements(store) as pending:
        pending.motion_residual(
            asset_id=raw.id,
            producer=VIDEO_RESIDUAL_PRODUCER,
            source_digest=source_metadata_digest(raw),
            measured={"residual": 0.1, "frames": 8},
        )
    calls.clear()
    assert source_metadata_digest(prepared.preparation_sources[raw.id]) == source_metadata_digest(
        raw
    )

    def refuse(*_args, **_kwargs):
        raise AssertionError("Cached canonical preparation must not download or decode")

    evidence = EvidencePreparation(
        AnnotationReadings(store, config, {}, include_captions=False),
        object(),
        tmp_path / "previews",
        EditorialRuntimePorts(
            prepare_annotations=partial(prepare_editorial_annotations, ports=providers),
            fetch_preview=refuse,
            fetch_faces=lambda *_args: (),
            fetch_playback_range=refuse,
        ),
        lambda: tmp_path,
    )
    return raw, prepared, evidence, calls


def test_promoted_favourite_reuses_the_raw_cached_motion_without_playback(tmp_path):
    _, prepared, evidence, calls = _cached_preparation(tmp_path)
    assert evidence(prepared, None, frozenset(prepared.candidate_ids)) == {}
    assert calls == []


def test_changed_source_checksum_still_owes_a_real_measurement(tmp_path):
    raw, _, evidence, _ = _cached_preparation(tmp_path)
    changed = raw.model_copy(update={"checksum": "a" * 40})
    prepared = prepare_editorial_source(
        EditorialSelectionRequest(scope=SourceScope(min_source_short_side=0)),
        EditorialDependencies(source_fetcher=lambda _scope: (changed,)),
    )
    with pytest.raises(AssertionError, match="must not download or decode"):
        evidence(prepared, None, frozenset(prepared.candidate_ids))


def test_legacy_constructor_without_raw_mapping_uses_its_source(tmp_path):
    raw, prepared, evidence, calls = _cached_preparation(tmp_path)
    legacy = replace(
        prepared, preparation_sources={}, candidates=(replace(prepared.candidates[0], source=raw),)
    )
    assert evidence(legacy, None, frozenset(legacy.candidate_ids)) == {}
    assert calls == []
