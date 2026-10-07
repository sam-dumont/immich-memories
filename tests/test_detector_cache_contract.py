"""Changing v1 producer semantics requires a new version and an explicit migration decision."""

import hashlib
import json
from pathlib import Path

from immich_memories.analysis import editorial_preparation_detectors as detectors
from immich_memories.analysis.editorial_clip_frames import CLIP_FRAMES_VERSION
from immich_memories.analysis.editorial_preparation_detector_frames import FRAME_WIDTH, FRAMES
from immich_memories.analysis.editorial_preparation_heads import PUBLIC_HEAD_VERSIONS
from immich_memories.config_models_editorial_preparation import EditorialPreparationConfig
from immich_memories.db.tables import head_facts
from immich_memories.triage import encoder, preprocess


def current_contract():
    bundle = EditorialPreparationConfig().head_bundle_path
    return {
        "contract": "detector-facts-v1",
        "primary_key": [column.name for column in head_facts.primary_key],
        "fields": [column.name for column in head_facts.columns],
        "versions": PUBLIC_HEAD_VERSIONS
        | detectors.DETECTOR_VERSIONS
        | {"clip_frames": CLIP_FRAMES_VERSION},
        "dino": {
            "model": encoder.DINOV2_SMALL_ID,
            "sha256": encoder.DINOV2_SMALL_ONNX_SHA256,
            "preprocess": preprocess.PREPROCESS_VERSION,
            "layout": encoder.LAYOUT_VERSION,
            "bundle_sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
        },
        "marqo": {
            "model": detectors.MARQO_ONNX_ID,
            "sha256": detectors.MARQO_ONNX_SHA256,
            "classes": list(detectors.MARQO_CLASSES),
            "side": detectors.MARQO_SIDE,
            "equivalent_stills": detectors.MARQO_STILL_EQUIVALENT,
        },
        "docling": {
            "model": detectors.DOCLING_REPO,
            "revision": detectors.DOCLING_REVISION,
            "classes": list(detectors.DOCLING_LABELS),
        },
        "sampling": {"frames": FRAMES, "width": FRAME_WIDTH},
    }


def test_v1_pins_payload_keys_models_labels_and_sampling():
    frozen = Path(__file__).parent / "fixtures/detector-cache-v1.json"
    assert current_contract() == json.loads(frozen.read_text()), (
        "A changed detector contract needs a new producer version and a documented compatibility "
        "migration. Do not silently overwrite the v1 snapshot."
    )


def test_switching_tiers_preserves_banked_detector_versions_and_gpu_reads():
    from immich_memories.analysis.editorial_shareability import load_detector_heads
    from immich_memories.config_loader import Config
    from immich_memories.config_tiers import apply_tier
    from tests.annotation_rows import add_rows, annotation_store

    config = Config(tier="gpu")
    versions = dict(config.editorial.head_versions)
    store = annotation_store()
    add_rows(
        store,
        "head_facts",
        *[
            {"asset_id": "picture", "head": head, "version": versions[head], "label": label}
            for head, label in (
                ("nsfw_marqo", "yes"),
                ("doc_docling", "table"),
                ("uncovered_person", "no"),
            )
        ],
    )
    assert (
        load_detector_heads(store, ["picture"], config.editorial.active_head_versions)["picture"][
            "nsfw_marqo"
        ]
        == "yes"
    )
    config.tier = "basic"
    apply_tier(config)
    assert config.tier == "basic"
    assert load_detector_heads(store, ["picture"], config.editorial.active_head_versions) == {
        "picture": {"uncovered_person": "no"}
    }
    config.tier = "gpu"
    apply_tier(config)
    assert config.editorial.head_versions == versions
    assert (
        load_detector_heads(store, ["picture"], config.editorial.active_head_versions)["picture"][
            "doc_docling"
        ]
        == "table"
    )


def test_a_live_photo_clip_reads_the_same_corrected_people_head_as_its_still():
    """#2079: the clip's detector rows go through the corroboration the annotation read applies,
    so a people head with no face behind it reads "none" on both."""
    from immich_memories.analysis.editorial_shareability import load_detector_heads
    from tests.annotation_rows import add_rows, annotation_store

    store = annotation_store()
    add_rows(
        store,
        "face_boxes",
        {"asset_id": "still", "named": False, "x1": 0.1, "y1": 0.1, "x2": 0.2, "y2": 0.2},
    )
    add_rows(
        store,
        "head_facts",
        {"asset_id": "clip", "head": "people", "version": "public-v1", "label": "group"},
        {"asset_id": "still", "head": "people", "version": "public-v1", "label": "group"},
    )

    heads = load_detector_heads(store, ["clip", "still"], {"people": "public-v1"})

    assert heads["clip"]["people"] == "none"
    assert heads["still"]["people"] == "group"
