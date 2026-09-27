"""What the client banks from the real service is the row the local producers would bank.

The service runs the application's own producers, so the comparison here holds the
model outputs fixed (stub encoders, stub detector probabilities) and checks that the
whole path from ``POST /facts`` to the SQLite row lands on the same head, version,
label, confidence and encoder key as the in-process banking code does for those outputs.
"""

from __future__ import annotations

from io import BytesIO

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from immich_memories.analysis import editorial_preparation_detectors as detectors
from immich_memories.analysis.editorial_preparation_detectors import _FACT_COLUMNS, _decided_rows
from immich_memories.analysis.editorial_preparation_heads import PUBLIC_HEAD_VERSIONS
from immich_memories.analysis.editorial_preparation_remote import prepare_remote_facts
from immich_memories.analysis.remote_facts import RemoteFactsClient
from immich_memories.cache.embedding_cache import HeadFactStore
from immich_memories.config_models_editorial import EditorialConfig
from immich_memories.config_models_inference import InferenceConfig
from immich_memories.db import Store, StoreLocation, open_store
from immich_memories.store.editorial_preparation import remember_head_rows
from immich_memories.triage.heads import HeadFact
from immich_memories_inference.app import create_app
from immich_memories_inference.producers import (
    DOC_DOCLING,
    HEADS,
    NSFW_MARQO,
    DetectorProducer,
    Fact,
    ProducerFacts,
)
from immich_memories_inference.runtime import ProducerRuntime
from immich_memories_inference.settings import InferenceSettings
from tests.annotation_rows import read_rows

ENCODER_KEY = "b" * 64
ASSETS = ("aa1", "bb2")


def picture() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (64, 48), (200, 120, 40)).save(buffer, "JPEG")
    return buffer.getvalue()


class FixedHeads:
    """# WHY: stands in for the DINOv2 encoder and the head bundle (88 MB of weights).
    The rule under test is the banking path, not the classifier."""

    name = HEADS

    @property
    def encoder_key(self) -> str:
        return ENCODER_KEY

    @property
    def versions(self) -> dict[str, str]:
        return dict(PUBLIC_HEAD_VERSIONS)

    def decide(self, image: bytes) -> ProducerFacts:
        return ProducerFacts(
            producer=self.name,
            encoder_key=self.encoder_key,
            facts=tuple(
                Fact(head=head, version=version, label="other", confidence=0.61)
                for head, version in PUBLIC_HEAD_VERSIONS.items()
            ),
        )


class StubMarqo:
    encoder_key = detectors.MARQO_ONNX_ID
    version = detectors.MARQO_VERSION
    head = NSFW_MARQO
    classes = detectors.MARQO_CLASSES

    def batch(self, images: list[Image.Image]) -> np.ndarray:
        return np.array([[0.83, 0.17]] * len(images), dtype=np.float32)


class StubDocling:
    encoder_key = detectors.DOCLING_REPO
    version = detectors.DOCLING_VERSION
    head = DOC_DOCLING
    classes = detectors.DOCLING_LABELS

    def batch(self, images: list[Image.Image]) -> np.ndarray:
        scores = np.full(len(detectors.DOCLING_LABELS), 0.01, dtype=np.float32)
        scores[-1] = 1.0 - 0.01 * (len(detectors.DOCLING_LABELS) - 1)
        return np.array([scores] * len(images), dtype=np.float32)


def store_at(tmp_path, name: str) -> Store:
    return open_store(location=StoreLocation(url=f"sqlite:///{tmp_path / name}"))


def rows(store: Store) -> set[tuple]:
    return {
        (
            row["asset_id"],
            row["head"],
            row["version"],
            row["label"],
            row["confidence"],
            row["encoder_key"],
        )
        for row in read_rows(store, "head_facts")
    }


def bank_locally(store: Store) -> None:
    """The in-process path: the engine's store call for heads, the worker's rows for detectors."""
    head_store = HeadFactStore(store)
    head_store.remember_facts(
        {
            asset_id: [
                HeadFact(head=head, label="other", confidence=0.61, version=version)
                for head, version in PUBLIC_HEAD_VERSIONS.items()
            ]
            for asset_id in ASSETS
        },
        encoder_key=ENCODER_KEY,
    )
    for detector in (StubMarqo(), StubDocling()):
        probabilities = detector.batch([Image.open(BytesIO(picture()))] * len(ASSETS))
        remember_head_rows(
            store,
            [
                dict(zip(_FACT_COLUMNS, row, strict=True))
                for row in _decided_rows(detector, ASSETS, probabilities)
            ],
        )


def stub_service(tmp_path):
    """The real app and the real client, over stub weights."""
    runtime = ProducerRuntime(
        {
            HEADS: FixedHeads,
            NSFW_MARQO: lambda: DetectorProducer(NSFW_MARQO, StubMarqo()),
            DOC_DOCLING: lambda: DetectorProducer(DOC_DOCLING, StubDocling()),
        }
    )
    return create_app(InferenceSettings(cache_dir=tmp_path), runtime=runtime)


def bank_remotely(app, store: Store) -> float | None:
    config = InferenceConfig(facts_base_url="http://inference.test:8092")
    versions = EditorialConfig().head_versions
    with (
        TestClient(app, base_url=config.facts_base_url) as http,
        RemoteFactsClient(config, client=http) as client,
    ):
        return prepare_remote_facts(
            pending={asset_id: dict(versions) for asset_id in ASSETS},
            store=store,
            client=client,
            concurrency=config.facts_concurrency,
            preview_for=lambda _asset_id: picture(),
            check_cancelled=lambda: None,
            progress=lambda *_: None,
            on_asset=lambda _asset_id: None,
        )


def test_the_client_banks_exactly_what_the_local_producers_would(tmp_path) -> None:
    remote_store = store_at(tmp_path, "remote.db")
    local_store = store_at(tmp_path, "local.db")
    versions = EditorialConfig().head_versions

    bank_remotely(stub_service(tmp_path), remote_store)
    bank_locally(local_store)

    banked = rows(remote_store)
    assert banked == rows(local_store)
    assert {(head, version) for _, head, version, *_ in banked} == set(versions.items())
    assert {label for _, head, _, label, *_ in banked if head == NSFW_MARQO} == {"yes"}


def test_the_client_reads_the_seconds_the_service_charged_itself(tmp_path) -> None:
    """Client and service have to agree on the header name, and nothing else checks it."""
    charged = bank_remotely(stub_service(tmp_path), store_at(tmp_path, "remote.db"))

    assert charged is not None
    assert 0 <= charged < 60
