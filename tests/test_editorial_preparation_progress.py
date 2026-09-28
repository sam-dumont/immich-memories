"""Preparation publishes worker progress even when producer batches do not align."""

from dataclasses import replace
from functools import partial

from immich_memories.analysis.editorial_preparation import prepare_editorial_annotations
from immich_memories.analysis.editorial_runtime_evidence import (
    AnnotationReadings,
    EvidencePreparation,
    ensure_annotation_store,
)
from immich_memories.analysis.editorial_runtime_ports import EditorialRuntimePorts
from immich_memories.analysis.selection_source import (
    EditorialDependencies,
    EditorialSelectionRequest,
    SourceScope,
    prepare_editorial_source,
)
from immich_memories.config_loader import Config
from immich_memories.operations.cut_progress import read_stage_progress
from tests.test_editorial_preparation import asset, preview, successful_ports


def _prepare_with_progress(tmp_path, updates):
    sources = [asset(f"photo-{index}") for index in range(45)]
    prepared = prepare_editorial_source(
        EditorialSelectionRequest(scope=SourceScope(min_source_short_side=0)),
        # WHY: generated source records stand in for the Immich API boundary.
        EditorialDependencies(source_fetcher=lambda _scope: sources),
    )
    config = Config(editorial={"preparation": {"tier": "no_captions", "batch_size": 32}})
    store = tmp_path / "annotations.sqlite"
    ensure_annotation_store(store)
    providers = successful_ports([])

    def detectors(**kwargs):
        # WHY: simulate two detector workers' progress without loading ONNX models.
        for update in updates:
            kwargs["progress"](*update)
        return providers.detectors(**kwargs)

    preparation = EvidencePreparation(
        readings=AnnotationReadings(store, config, {}),
        client=object(),
        thumbnail_cache=tmp_path / "previews",
        ports=EditorialRuntimePorts(
            prepare_annotations=partial(
                prepare_editorial_annotations, ports=replace(providers, detectors=detectors)
            ),
            # WHY: use a generated preview at the Immich media boundary.
            fetch_preview=lambda _client, _asset: preview(),
            fetch_faces=lambda _client, _asset: (),
        ),
        artifact_dir=lambda: tmp_path,
    )
    published = []
    labels = {label for label, _, _ in updates}

    def observe(update):
        assert read_stage_progress(tmp_path) == update
        if update.label in labels:
            published.append((update.label, update.done, update.total))

    exclusions = preparation(prepared, observe, frozenset(prepared.candidate_ids))

    assert exclusions == {}
    return published


def test_detector_progress_continues_after_a_partial_producer_batch(tmp_path):
    updates = [("detectors", done, 90) for done in (0, 32, 45, 77, 90)]

    published = _prepare_with_progress(tmp_path, updates)

    assert published == [("detectors", done, 90) for done in (0, 32, 77, 90)]


def test_stage_changes_resets_and_completion_are_visible_between_batches(tmp_path):
    updates = [
        ("detectors", 0, 100),
        ("detectors", 32, 100),
        ("detectors", 45, 100),
        ("detectors", 40, 100),
        ("detectors", 41, 100),
        ("detectors", 7, 100),
        ("detectors", 0, 100),
        ("detectors", 5, 120),
        ("next detector", 5, 120),
        ("next detector", 6, 120),
        ("next detector", 120, 120),
    ]

    published = _prepare_with_progress(tmp_path, updates)

    assert published == [
        ("detectors", 0, 100),
        ("detectors", 32, 100),
        ("detectors", 40, 100),
        ("detectors", 7, 100),
        ("detectors", 0, 100),
        ("detectors", 5, 120),
        ("next detector", 5, 120),
        ("next detector", 120, 120),
    ]
