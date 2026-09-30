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
