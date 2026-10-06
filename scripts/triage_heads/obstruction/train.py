#!/usr/bin/env python3
"""Rebuild the finger-over-the-lens patch head (#2022) from public images alone, deterministically.

Trains a per-patch logistic probe over DINOv2-small tokens to answer, patch by patch, "is this
a finger over the lens." Positives are synthetic: a public negative image with a defocused,
skin-toned shape pasted over one of its edges, the same recipe a human reviewer judged
plausible against real finger-over-the-lens photographs. Negatives are the same public images,
unmodified. No photograph by the package's owner, and no owner-derived weight, is read or
written by this script.

    uv run python -m scripts.triage_heads.obstruction.train \
        --corpus-dir /path/to/public-corpus --out bundled_heads/public-obstruction-v1.npz

The corpus directory holds a Wikimedia Commons ``neg/`` pull and its ``neg_meta.json``
attribution manifest (id, license, page), in the shape `scripts/triage_heads/public_corpus.py`
produces for the other heads. Every array in the output bundle is a model coefficient; no
pixels are carried forward.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from immich_memories.triage.encoder import DinoEncoder
from immich_memories.triage.heads import PatchHeadBundle
from immich_memories.triage.preprocess import CROP_SIZE, IMAGENET_MEAN, IMAGENET_STD

SEED = 0
L2 = 10.0
ITERS = 800
SYNTH_COUNT = 240
NEG_COUNT = 240
MAX_TRAINING_PATCHES = 50_000
PATCH_GRID = 16
PATCH_SIZE = CROP_SIZE // PATCH_GRID

# Candidate finger/skin tones (R, G, B), the recipe `report.private.md` section 5 names.
SKIN_TONES = (
    (205, 160, 140), (225, 175, 155), (190, 120, 100), (150, 95, 75), (110, 60, 45),
    (230, 140, 140), (170, 70, 60), (95, 45, 38), (240, 200, 180), (215, 170, 150),
    (200, 150, 120),
)  # fmt: skip


def _crop224_rgb(path: Path) -> np.ndarray:
    """The same resize-short-side-256, centre-crop-224 geometry `preprocess_image_bytes` uses."""
    with Image.open(path) as handle:
        image = handle.convert("RGB")
    width, height = image.size
    if width <= height:
        resized = (256, round(height * 256 / width))
    else:
        resized = (round(width * 256 / height), 256)
    image = image.resize(resized, Image.Resampling.BICUBIC)
    left, top = (resized[0] - CROP_SIZE) // 2, (resized[1] - CROP_SIZE) // 2
    image = image.crop((left, top, left + CROP_SIZE, top + CROP_SIZE))
    return np.asarray(image, dtype=np.uint8)


def _normalized_tensor(rgb_uint8: np.ndarray) -> np.ndarray:
    pixels = rgb_uint8.astype(np.float32) / 255.0
    normalized = (pixels - IMAGENET_MEAN) / IMAGENET_STD
    return np.ascontiguousarray(normalized.transpose(2, 0, 1), dtype=np.float32)


def _composite_finger(rgb: np.ndarray, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """Paste a defocused, skin-toned shape over one edge; return the per-pixel alpha mask."""
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR).astype(np.float32)
    h, w = bgr.shape[:2]
    side = min(h, w)
    mask = np.zeros((h, w), np.float32)
    strokes = 1 if rng.random() < 0.75 else 2
    edge = rng.integers(4)
    for stroke in range(strokes):
        width = side * rng.uniform(0.25, 0.8)
        length = side * rng.uniform(0.35, 0.9)
        t = rng.choice([rng.uniform(0, 0.3), rng.uniform(0.7, 1.0), rng.uniform(0.2, 0.8)])
        if edge == 0:
            origin, angle = (t * w, -0.1 * side), np.pi / 2
        elif edge == 1:
            origin, angle = (t * w, h + 0.1 * side), -np.pi / 2
        elif edge == 2:
            origin, angle = (-0.1 * side, t * h), 0.0
        else:
            origin, angle = (w + 0.1 * side, t * h), np.pi
        angle += rng.uniform(-0.7, 0.7) + stroke * 0.35
        end = (origin[0] + np.cos(angle) * length, origin[1] + np.sin(angle) * length)
        cv2.line(
            mask, (int(origin[0]), int(origin[1])), (int(end[0]), int(end[1])), 1.0, int(width)
        )
        cv2.circle(mask, (int(end[0]), int(end[1])), int(width / 2), 1.0, -1)
    sigma = side * rng.uniform(0.03, 0.09)
    alpha = cv2.GaussianBlur(mask, (0, 0), sigma)
    alpha = np.clip(alpha * rng.uniform(1.0, 1.4), 0, 1)
    base = np.array(SKIN_TONES[rng.integers(len(SKIN_TONES))], np.float32)[::-1]
    base = base * rng.uniform(0.6, 1.25) * (bgr.mean() / 128) ** 0.5
    fill = cv2.GaussianBlur(np.broadcast_to(base, bgr.shape).copy(), (0, 0), 3)
    noise = np.asarray(rng.normal(0, rng.uniform(1, 4), bgr.shape), dtype=np.float32)
    fill = fill + noise
    out = bgr * (1 - alpha[..., None]) + fill * alpha[..., None]
    composited_rgb = cv2.cvtColor(np.clip(out, 0, 255).astype(np.uint8), cv2.COLOR_BGR2RGB)
    return composited_rgb, alpha


def _patch_labels(alpha: np.ndarray) -> np.ndarray:
    grid = alpha.reshape(PATCH_GRID, PATCH_SIZE, PATCH_GRID, PATCH_SIZE).mean(axis=(1, 3))
    return grid.reshape(-1)


def _fit(features: np.ndarray, labels: np.ndarray, *, l2: float, iters: int, lr: float = 0.5):
    """Standardized logistic regression, class-balanced, batch gradient descent."""
    mean, scale = features.mean(0), features.std(0) + 1e-6
    standardized = (features - mean) / scale
    weights = np.zeros(standardized.shape[1])
    bias = 0.0
    class_weight = (labels == 0).sum() / max(1, (labels == 1).sum())
    sample_weight = np.where(labels == 1, class_weight, 1.0)
    sample_weight = sample_weight / sample_weight.mean()
    for _ in range(iters):
        prediction = 1 / (1 + np.exp(-(standardized @ weights + bias)))
        gradient = sample_weight * (prediction - labels)
        weights -= lr * (standardized.T @ gradient / len(labels) + l2 * weights / len(labels))
        bias -= lr * gradient.mean()
    return mean, scale, weights, bias


def _training_rows(
    corpus_dir: Path, encoder: DinoEncoder, rng: np.random.Generator
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    neg_files = sorted((corpus_dir / "neg").glob("*.jpg"))
    if len(neg_files) < SYNTH_COUNT + NEG_COUNT:
        raise ValueError(f"{corpus_dir}: need at least {SYNTH_COUNT + NEG_COUNT} neg/ images")
    chosen = np.sort(rng.choice(len(neg_files), size=SYNTH_COUNT + NEG_COUNT, replace=False))
    synth_files = [neg_files[i] for i in chosen[:SYNTH_COUNT]]
    plain_files = [neg_files[i] for i in chosen[SYNTH_COUNT:]]
    features, labels = [], []
    used: list[str] = []
    for index, path in enumerate(synth_files):
        composited, alpha = _composite_finger(
            _crop224_rgb(path), np.random.default_rng(SEED * 1_000_003 + index)
        )
        _, tokens = encoder.embed_with_patches(_normalized_tensor(composited)[None])
        patch_alpha = _patch_labels(alpha)
        keep = (patch_alpha > 0.5) | (patch_alpha < 0.1)
        features.append(tokens[0][keep])
        labels.append((patch_alpha[keep] > 0.5).astype(np.float64))
        used.append(path.name)
    for path in plain_files:
        _, tokens = encoder.embed_with_patches(_normalized_tensor(_crop224_rgb(path))[None])
        features.append(tokens[0])
        labels.append(np.zeros(PATCH_GRID * PATCH_GRID))
        used.append(path.name)
    return np.concatenate(features).astype(np.float64), np.concatenate(labels), used


def _provenance(corpus_dir: Path, used_files: list[str], bundle_path: Path, seed: int) -> str:
    meta = json.loads((corpus_dir / "neg_meta.json").read_text())
    by_file = {str(entry.get("file", "")).rsplit("/", 1)[-1]: entry for entry in meta.values()}
    lines = [
        "# Public finger-over-the-lens probe",
        "",
        f"`{bundle_path.name}` is a per-patch logistic probe over DINOv2-small patch tokens, "
        f"trained by `scripts/triage_heads/obstruction/train.py` with a fixed seed ({seed}). "
        "It contains no owner photograph, no owner-derived weight, and no identity. "
        f"SHA-256: `{hashlib.sha256(bundle_path.read_bytes()).hexdigest()}`.",
        "",
        "## Positives: synthetic composites on public negatives",
        "",
        "Each positive is one of the Commons negatives below with a defocused, skin-toned "
        "shape pasted over a random edge (`_composite_finger`): 1-2 strokes, random width, "
        "length, entry edge and skin tone, Gaussian-blurred to a soft boundary, with "
        "Gaussian pixel noise. The per-pixel alpha is the training label, downsampled to the "
        "16x16 patch grid; a patch is a positive example above alpha 0.5, a negative below 0.1, "
        "and dropped in between.",
        "",
        "## Negatives and composite bases: Commons images",
        "",
        "| file | license | page |",
        "|---|---|---|",
    ]
    for name in sorted(set(used_files)):
        entry = by_file.get(name, {})
        lines.append(f"| {name} | {entry.get('license', '?')} | {entry.get('page', '?')} |")
    lines += [
        "",
        "Source: the CC-licensed Wikimedia Commons pull `scripts/triage_heads/public_corpus.py` "
        "produces; licenses and attribution pages are recorded above. Images are not "
        "redistributed with this bundle; the repository's license applies to the training and "
        "serving code.",
        "",
        "This head is shipped as a rank-only warning (`OBSTRUCTED (edge)`): a flagged picture "
        "loses to a clean sibling of the same moment and is never dropped on its own. See "
        "`docs-site/docs/how-it-chooses/` and `src/immich_memories/analysis/editorial_obstruction.py`.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--corpus-dir", type=Path, required=True)
    parser.add_argument(
        "--encoder-path",
        type=Path,
        default=Path("~/.immich-memories/models/triage/dinov2-small.onnx").expanduser(),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parents[3]
        / "src/immich_memories/triage/bundled_heads/public-obstruction-v1.npz",
    )
    parser.add_argument("--provider", default="cpu")
    args = parser.parse_args(argv)

    encoder = DinoEncoder.open(args.encoder_path, provider=args.provider)
    rng = np.random.default_rng(SEED)
    features, labels, used_files = _training_rows(args.corpus_dir, encoder, rng)
    if len(features) > MAX_TRAINING_PATCHES:
        subsample_rng = np.random.default_rng(SEED)
        selection = subsample_rng.choice(len(features), MAX_TRAINING_PATCHES, replace=False)
        features, labels = features[selection], labels[selection]
    mean, scale, weights, bias = _fit(features, labels, l2=L2, iters=ITERS)
    bundle = PatchHeadBundle(
        encoder_key=encoder.key,
        name="obstruction",
        version="public-obstruction-v1",
        mu=mean,
        sd=scale,
        w=weights,
        b=float(bias),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    bundle.save(args.out)
    args.out.with_suffix(".md").write_text(_provenance(args.corpus_dir, used_files, args.out, SEED))
    print(f"wrote {args.out} ({len(features)} training patches, {labels.sum():.0f} positive)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
