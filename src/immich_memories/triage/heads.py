"""Head weights as one npz bundle: the PCA projection and every linear head behind it.

The bundle is the unit that ships. It is bound to one encoder key so a head can
never be run on features it was not trained on.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

BUNDLE_SCHEMA = "triage-head-bundle-v1"
PATCH_BUNDLE_SCHEMA = "triage-patch-head-bundle-v1"
_META_KEY = "meta"
PATCH_GRID = 16


@dataclass(frozen=True)
class HeadFact:
    head: str
    label: str
    confidence: float
    version: str


@dataclass(frozen=True)
class PcaWeights:
    mean: np.ndarray
    components: np.ndarray

    def project(self, packs: np.ndarray) -> np.ndarray:
        array = np.asarray(packs, dtype=np.float32)
        if array.ndim != 2 or array.shape[1] != self.mean.shape[0]:
            raise ValueError(f"PCA expected [n, {self.mean.shape[0]}] packs, got {array.shape}")
        # Training projected FP32 → stored FP16 → FP32; serving must round the same way.
        projected = (array - self.mean) @ self.components.T
        return projected.astype(np.float16).astype(np.float32)


@dataclass(frozen=True)
class HeadWeights:
    name: str
    version: str
    classes: tuple[str, ...]
    coef: np.ndarray
    intercept: np.ndarray

    def probabilities(self, features: np.ndarray) -> np.ndarray:
        logits = features @ self.coef.T + self.intercept
        logits = logits - logits.max(axis=1, keepdims=True)
        exp = np.exp(logits)
        return (exp / exp.sum(axis=1, keepdims=True)).astype(np.float32)


@dataclass(frozen=True)
class HeadBundle:
    encoder_key: str
    pca: PcaWeights
    heads: tuple[HeadWeights, ...]

    def decide(self, packs: np.ndarray) -> dict[str, list[HeadFact]]:
        """One fact per head per pack: the argmax label and its probability."""
        features = self.pca.project(packs)
        facts: dict[str, list[HeadFact]] = {}
        for head in self.heads:
            probabilities = head.probabilities(features)
            winners = probabilities.argmax(axis=1)
            facts[head.name] = [
                HeadFact(
                    head=head.name,
                    label=head.classes[int(index)],
                    confidence=float(probabilities[row, index]),
                    version=head.version,
                )
                for row, index in enumerate(winners)
            ]
        return facts

    def save(self, path: Path) -> None:
        arrays: dict[str, np.ndarray] = {
            "pca_mean": self.pca.mean.astype(np.float32),
            "pca_components": self.pca.components.astype(np.float32),
        }
        meta = {
            "schema": BUNDLE_SCHEMA,
            "encoder_key": self.encoder_key,
            "heads": [
                {"name": head.name, "version": head.version, "classes": list(head.classes)}
                for head in self.heads
            ],
        }
        for head in self.heads:
            arrays[f"{head.name}__coef"] = head.coef.astype(np.float32)
            arrays[f"{head.name}__intercept"] = head.intercept.astype(np.float32)
        arrays[_META_KEY] = np.asarray(json.dumps(meta, sort_keys=True))
        with path.open("wb") as handle:
            np.savez_compressed(handle, allow_pickle=False, **arrays)

    @classmethod
    def load(cls, path: Path) -> HeadBundle:
        with np.load(path, allow_pickle=False) as payload:
            meta = json.loads(str(payload[_META_KEY]))
            if meta.get("schema") != BUNDLE_SCHEMA:
                raise ValueError(f"{path}: not a {BUNDLE_SCHEMA} bundle")
            pca = PcaWeights(mean=payload["pca_mean"], components=payload["pca_components"])
            heads = tuple(
                HeadWeights(
                    name=entry["name"],
                    version=entry["version"],
                    classes=tuple(entry["classes"]),
                    coef=payload[f"{entry['name']}__coef"],
                    intercept=payload[f"{entry['name']}__intercept"],
                )
                for entry in meta["heads"]
            )
        return cls(encoder_key=str(meta["encoder_key"]), pca=pca, heads=heads)


@dataclass(frozen=True)
class PatchHeadBundle:
    """A per-patch logistic probe over raw DINOv2 tokens, not the pooled, PCA'd pack.

    `HeadBundle` answers one label per picture off the pooled pack; this answers one
    probability per 14x14 patch off the tokens the pack discards, for a question the pack
    cannot hold: *where* in the frame, not just whether. The probe standardizes its own
    input (`mu`, `sd`), matching how it was fit.
    """

    encoder_key: str
    name: str
    version: str
    mu: np.ndarray
    sd: np.ndarray
    w: np.ndarray
    b: float

    def patch_probabilities(self, tokens: np.ndarray) -> np.ndarray:
        """``[n, 256, 384]`` patch tokens → ``[n, 16, 16]`` per-patch probabilities."""
        array = np.asarray(tokens, dtype=np.float64)
        if array.ndim != 3 or array.shape[1:] != (PATCH_GRID * PATCH_GRID, self.mu.shape[0]):
            raise ValueError(
                f"expected [n, {PATCH_GRID * PATCH_GRID}, {self.mu.shape[0]}] tokens, "
                f"got {array.shape}"
            )
        standardized = (array.reshape(-1, self.mu.shape[0]) - self.mu) / self.sd
        logits = standardized @ self.w + self.b
        probabilities = 1.0 / (1.0 + np.exp(-logits))
        return probabilities.reshape(-1, PATCH_GRID, PATCH_GRID).astype(np.float32)

    def save(self, path: Path) -> None:
        meta = {
            "schema": PATCH_BUNDLE_SCHEMA,
            "encoder_key": self.encoder_key,
            "name": self.name,
            "version": self.version,
            "b": self.b,
        }
        with path.open("wb") as handle:
            np.savez_compressed(
                handle,
                allow_pickle=False,
                mu=self.mu.astype(np.float64),
                sd=self.sd.astype(np.float64),
                w=self.w.astype(np.float64),
                meta=np.asarray(json.dumps(meta, sort_keys=True)),
            )

    @classmethod
    def load(cls, path: Path) -> PatchHeadBundle:
        with np.load(path, allow_pickle=False) as payload:
            meta = json.loads(str(payload["meta"]))
            if meta.get("schema") != PATCH_BUNDLE_SCHEMA:
                raise ValueError(f"{path}: not a {PATCH_BUNDLE_SCHEMA} bundle")
            return cls(
                encoder_key=str(meta["encoder_key"]),
                name=str(meta["name"]),
                version=str(meta["version"]),
                mu=payload["mu"],
                sd=payload["sd"],
                w=payload["w"],
                b=float(meta["b"]),
            )
