"""The document check, run on the real pinned models, holds maps and keeps aerial photographs.

The unit suite replays what the two models answered on these public pictures
(`tests/fixtures/document_check/measured.json`); this runs the models again, so the record is
proven to be what they say. It needs the pinned Docling snapshot in the Hugging Face cache and
the DINOv2 export `models fetch` downloads, and skips without them.
"""

from __future__ import annotations

import io
import json
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from immich_memories.analysis.facts.carrier_eligibility import corroborated_document
from immich_memories.analysis.preparation.detectors import Docling, decide
from immich_memories.config.models.editorial_preparation import EditorialPreparationConfig
from immich_memories.config.models.triage import TriageConfig
from immich_memories.triage.encoder import DinoEncoder
from immich_memories.triage.heads import HeadBundle
from immich_memories.triage.preprocess import preprocess_image_bytes

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "document_check"
LIBRARY = Path(__file__).resolve().parents[2] / "e2e" / "fixtures" / "library"
MEASURED = json.loads((FIXTURES / "measured.json").read_text())


def picture_path(name: str) -> Path:
    """A fixture picture, or one of the demo library's summit views it names by file."""
    own = FIXTURES / name
    return own if own.exists() else LIBRARY / name


def measure(paths: Sequence[Path]) -> dict[str, dict[str, list]]:
    """The document head's and the frame head's answers, as `prepare` banks them."""
    try:
        docling = Docling(allow_downloads=False, cache_dir=None, provider="cpu")
    except Exception as exc:  # noqa: BLE001 - any missing or unreadable snapshot means skip
        pytest.skip(f"the pinned Docling snapshot is not cached here: {exc}")
    encoder_path = TriageConfig().encoder_path
    if not encoder_path.is_file():
        pytest.skip(f"the pinned DINOv2 export is not at {encoder_path}")
    encoder = DinoEncoder.open(encoder_path, provider="cpu")
    bundle = HeadBundle.load(EditorialPreparationConfig().head_bundle_path)
    images = []
    for path in paths:
        with Image.open(path) as image:
            images.append(image.convert("RGB"))
    documents = docling.batch(images)
    packs = []
    for image in images:
        encoded = io.BytesIO()
        image.save(encoded, "JPEG", quality=95)
        packs.append(preprocess_image_bytes(encoded.getvalue()))
    frames = bundle.decide(encoder.embed(np.stack(packs)))["frame_kind"]
    out = {}
    for row, path in enumerate(paths):
        scores = dict(zip(docling.classes, map(float, documents[row]), strict=True))
        label, confidence = decide(docling.head, scores)
        frame = frames[row]
        out[path.name] = {
            "doc_docling": [label, confidence],
            "frame_kind": [frame.label, round(frame.confidence, 5)],
        }
    return out


def test_the_real_models_answer_what_the_record_says():
    names = sorted(MEASURED["pictures"])

    measured = measure([picture_path(name) for name in names])

    for name in names:
        recorded = MEASURED["pictures"][name]
        for head in ("doc_docling", "frame_kind"):
            assert measured[name][head][0] == recorded[head][0], (name, head)
            assert measured[name][head][1] == pytest.approx(recorded[head][1], abs=0.01), (
                name,
                head,
            )
        document = corroborated_document(
            measured[name]["doc_docling"][0],
            frame_kind=measured[name]["frame_kind"][0],
            frame_confidence=measured[name]["frame_kind"][1],
        )
        assert (document == "geographical_map") is recorded["held"], name
