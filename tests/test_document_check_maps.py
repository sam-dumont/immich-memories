"""A map holds a picture out of every film; a photograph of real ground seen from above does not.

The document head reads aerial, drone and summit views as maps (#2544). The frame head, read
beside it, tells them apart. These tests drive the read every selection path goes through, on
the answers the real models gave on public pictures (`tests/fixtures/document_check/`).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest

from immich_memories.analysis.annotation_lines import StoredAnnotationLineReader
from immich_memories.analysis.editorial_carrier_eligibility import excluded_carrier_sources
from immich_memories.analysis.editorial_contracts import EditorialCandidate
from immich_memories.analysis.editorial_shareability import load_detector_heads
from immich_memories.store.asset_annotations import AssetAnnotationFactRepository
from tests.annotation_rows import add_rows, annotation_store
from tests.conftest import make_asset

MEASURED = json.loads(
    (Path(__file__).parent / "fixtures" / "document_check" / "measured.json").read_text()
)["pictures"]
HEADS = {"doc_docling": "det-v2", "frame_kind": "public-v1"}
CAPTURED = datetime(2025, 7, 21, 16, tzinfo=UTC)


def _bank(store, asset_id: str, document: tuple[str, float], frame: tuple[str, float]) -> None:
    add_rows(
        store,
        "head_facts",
        {
            "asset_id": asset_id,
            "head": "doc_docling",
            "version": HEADS["doc_docling"],
            "label": document[0],
            "confidence": document[1],
        },
        {
            "asset_id": asset_id,
            "head": "frame_kind",
            "version": HEADS["frame_kind"],
            "label": frame[0],
            "confidence": frame[1],
        },
    )


def _document_head(store, asset_id: str, versions=HEADS) -> str:
    facts = AssetAnnotationFactRepository(
        store, description_model=None, head_versions=versions, pixel_producer_key="pixel-v1"
    ).facts_for((asset_id,))
    return dict(facts.as_mapping()[asset_id].heads)["doc_docling"]


def _candidate(asset_id: str) -> EditorialCandidate:
    return EditorialCandidate(
        asset_id=asset_id,
        taken_at=CAPTURED,
        source=make_asset(asset_id, file_created_at=CAPTURED),
        media_kind="photo",
        live_photo_stitch_member_ids=(),
        rendering_family_id=None,
        favourite=False,
        shippable_duration=0.0,
        grounded_annotations=(),
    )


@pytest.mark.parametrize("name", sorted(MEASURED))
def test_the_document_check_holds_the_maps_and_keeps_the_aerial_photographs(name):
    store = annotation_store()
    picture = MEASURED[name]
    asset_id = str(uuid5(NAMESPACE_URL, name))
    _bank(store, asset_id, tuple(picture["doc_docling"]), tuple(picture["frame_kind"]))
    lines = StoredAnnotationLineReader(
        store=store,
        candidates=(_candidate(asset_id),),
        description_model=None,
        head_versions=HEADS,
        pixel_producer_key="pixel-v1",
    ).lines_for((asset_id,))

    excluded = excluded_carrier_sources(
        lines.as_mapping(), heads_of={asset_id: dict(lines.lines[0].heads)}
    )

    if picture["held"]:
        assert excluded == {asset_id: "document-head:geographical_map"}
    else:
        assert asset_id not in excluded


def test_a_map_the_frame_head_only_leans_towards_a_place_stays_a_map():
    """A shaded-relief map reads as a place often enough; only near-certainty overrules it."""
    store = annotation_store()
    _bank(store, "relief-map", ("geographical_map", 0.99), ("place_or_scenery", 0.93))

    assert _document_head(store, "relief-map") == "geographical_map"


def test_the_frame_head_never_overrules_any_other_document_label():
    store = annotation_store()
    _bank(store, "whiteboard", ("table", 0.97), ("place_or_scenery", 0.9999))

    assert _document_head(store, "whiteboard") == "table"


def test_an_owner_frame_head_bank_is_not_the_one_the_band_was_measured_on():
    store = annotation_store()
    add_rows(
        store,
        "head_facts",
        {
            "asset_id": "view",
            "head": "doc_docling",
            "version": "det-v2",
            "label": "geographical_map",
        },
        {
            "asset_id": "view",
            "head": "frame_kind",
            "version": "owner-v1",
            "label": "place_or_scenery",
            "confidence": 1.0,
        },
    )

    head = _document_head(store, "view", {"doc_docling": "det-v2", "frame_kind": "owner-v1"})

    assert head == "geographical_map"


def test_a_clip_seen_from_above_reads_as_a_photograph_too():
    """An attached clip is read from the bank directly; it gets the same corrected label."""
    store = annotation_store()
    _bank(store, "drone-clip", ("geographical_map", 0.98), ("place_or_scenery", 0.9995))
    _bank(store, "map-clip", ("geographical_map", 0.98), ("screen_or_document", 0.9))

    heads = load_detector_heads(store, ["drone-clip", "map-clip"], HEADS)

    assert heads["drone-clip"]["doc_docling"] == "photograph"
    assert heads["map-clip"]["doc_docling"] == "geographical_map"
