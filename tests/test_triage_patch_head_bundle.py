"""The patch-level probe bundle: one probability per 14x14 patch, not one per picture."""

from __future__ import annotations

import numpy as np
import pytest

from immich_memories.triage.heads import PatchHeadBundle


def _bundle() -> PatchHeadBundle:
    rng = np.random.default_rng(0)
    return PatchHeadBundle(
        encoder_key="encoder-key-abc",
        name="obstruction",
        version="public-obstruction-v1",
        mu=np.zeros(4),
        sd=np.ones(4),
        w=rng.normal(size=4),
        b=0.0,
    )


def test_patch_probabilities_shape_one_per_patch():
    bundle = _bundle()
    tokens = np.zeros((2, 256, 4))

    probabilities = bundle.patch_probabilities(tokens)

    assert probabilities.shape == (2, 16, 16)
    assert np.all((probabilities >= 0) & (probabilities <= 1))


def test_patch_probabilities_rejects_the_wrong_token_width():
    bundle = _bundle()

    with pytest.raises(ValueError, match="expected"):
        bundle.patch_probabilities(np.zeros((1, 256, 9)))


def test_save_and_load_round_trips_the_probe(tmp_path):
    bundle = _bundle()
    path = tmp_path / "probe.npz"
    bundle.save(path)

    loaded = PatchHeadBundle.load(path)

    assert loaded.encoder_key == bundle.encoder_key
    assert loaded.name == bundle.name
    assert loaded.version == bundle.version
    assert loaded.b == bundle.b
    assert np.array_equal(loaded.w, bundle.w)
    tokens = np.random.default_rng(1).normal(size=(3, 256, 4))
    assert np.allclose(loaded.patch_probabilities(tokens), bundle.patch_probabilities(tokens))


def test_load_refuses_a_file_that_is_not_a_patch_head_bundle(tmp_path):
    from immich_memories.triage.heads import HeadBundle, HeadWeights, PcaWeights

    other = HeadBundle(
        encoder_key="k",
        pca=PcaWeights(mean=np.zeros(2), components=np.eye(2)),
        heads=(
            HeadWeights(
                name="x",
                version="v1",
                classes=("a", "b"),
                coef=np.zeros((2, 2)),
                intercept=np.zeros(2),
            ),
        ),
    )
    path = tmp_path / "wrong.npz"
    other.save(path)

    with pytest.raises(ValueError, match="not a"):
        PatchHeadBundle.load(path)
