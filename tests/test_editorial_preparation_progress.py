"""Preparation publishes worker progress even when producer batches do not align."""

from dataclasses import replace
from functools import partial

import pytest

from immich_memories.analysis.editorial_preparation import prepare_editorial_annotations
from immich_memories.analysis.editorial_runtime_evidence import (
    AnnotationReadings,
    EvidencePreparation,
)
from immich_memories.analysis.editorial_runtime_ports import EditorialRuntimePorts
from immich_memories.analysis.selection_source import (
    EditorialDependencies,
    EditorialSelectionRequest,
    SourceScope,
    prepare_editorial_source,
)
from immich_memories.config_loader import Config
from immich_memories.db import open_store
from immich_memories.operations.cut_progress import read_stage_progress
from tests.test_editorial_preparation import asset, preview, successful_ports


def _prepare_with_progress(tmp_path, updates, *, before_update=lambda: None):
    sources = [asset(f"photo-{index}") for index in range(45)]
    prepared = prepare_editorial_source(
        EditorialSelectionRequest(scope=SourceScope(min_source_short_side=0)),
        # WHY: generated source records stand in for the Immich API boundary.
        EditorialDependencies(source_fetcher=lambda _scope: sources),
    )
    config = Config(tier="gpu", editorial={"preparation": {"batch_size": 32}})
    store = open_store()
    providers = successful_ports([])

    def detectors(**kwargs):
        # WHY: simulate two detector workers' progress without loading ONNX models.
        for update in updates:
            before_update()
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

    # Entry counts the actual fixture workload; the worker then publishes its own totals.
    assert published == [("detectors", 0, 2)] + [
        ("detectors", done, 90) for done in (0, 32, 77, 90)
    ]


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
        ("detectors", 0, 2),
        ("detectors", 0, 100),
        ("detectors", 32, 100),
        ("detectors", 40, 100),
        ("detectors", 7, 100),
        ("detectors", 0, 100),
        ("detectors", 5, 120),
        ("next detector", 5, 120),
        ("next detector", 120, 120),
    ]


@pytest.mark.parametrize("producer", ["captions", "detectors"])
def test_a_cold_provider_is_announced_before_its_first_answer(tmp_path, producer):
    from tests.test_editorial_preparation import run

    updates = []
    providers = successful_ports([])

    def model(**kwargs):
        # WHY: only replace the model boundary; preparation and its store are real.
        total = (
            len(kwargs["asset_ids"])
            if producer == "captions"
            else sum(len(ids) for ids in kwargs["pending"].values())
        )
        assert updates[-1] == (producer, 0, total)
        return getattr(providers, producer)(**kwargs)

    result = run(
        tmp_path,
        ports=replace(providers, **{producer: model}),
        fetch_preview=lambda _asset: preview(),
        progress=lambda stage, done, total: updates.append((stage, done, total)),
    )

    assert result.complete, result.failures


def test_slow_results_publish_without_waiting_for_a_full_batch(tmp_path, monkeypatch):
    # WHY: advance time at the model boundary instead of sleeping for each clip.
    import time

    now = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])

    def completed_one():
        now[0] += 5.0

    updates = [("detectors", done, 90) for done in (0, 1, 2)]
    published = _prepare_with_progress(tmp_path, updates, before_update=completed_one)

    assert ("detectors", 1, 90) in published
    assert ("detectors", 2, 90) in published
