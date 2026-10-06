"""Prepare revision-pinned ACE-Step weights before upstream can auto-download them."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

MAIN_REPO = "ACE-Step/Ace-Step1.5"
CHECKPOINT_REVISIONS = {
    "ACE-Step/Ace-Step1.5": "19671f406d603126926c1b7e2adc169acbcade22",
    "ACE-Step/acestep-5Hz-lm-0.6B": "148d8ea0225bdab342ee1ae3a354275ccd60ca80",
    "ACE-Step/acestep-5Hz-lm-4B": "0a3ec94b557aea7d508da38b31cfe7341f6ff737",
    "ACE-Step/acestep-v15-turbo-shift3": "625a282f7c8d882c930a5e500be4c82800f84fb4",
    "ACE-Step/acestep-v15-sft": "c410d249e71ea9385a7b586865e65b1473e1098d",
    "ACE-Step/acestep-v15-base": "e432212fec32b8965a14ffa57ae653438d6abd14",
    "ACE-Step/acestep-v15-turbo-shift1": "5b86586cc1faecd5214281b05440c8903b6da20f",
    "ACE-Step/acestep-v15-turbo-continuous": "f8e893768347fd42f5988e07d1d80675fc3e5718",
    "ACE-Step/acestep-v15-xl-base": "220c1166efbdd9583eafcb12eb160594bbfcb241",
    "ACE-Step/acestep-v15-xl-sft": "d06de46b4622f781cf07f4a013a67d591ca52819",
    "ACE-Step/acestep-v15-xl-turbo": "d4a0b288b83ebb7e25a8c0b32c573c22e134e8ee",
}
_MAIN_COMPONENTS = ("vae", "Qwen3-Embedding-0.6B", "acestep-v15-turbo", "acestep-5Hz-lm-1.7B")
_WEIGHT_FILES = (
    "model.safetensors",
    "model.safetensors.index.json",
    "pytorch_model.bin",
    "pytorch_model.bin.index.json",
    "diffusion_pytorch_model.safetensors",
    "diffusion_pytorch_model.safetensors.index.json",
    "diffusion_pytorch_model.bin",
    "diffusion_pytorch_model.bin.index.json",
)
# A changed pin gets a fresh directory, so an old unpinned cache cannot satisfy it.
CHECKPOINT_SET = hashlib.sha256(
    json.dumps(CHECKPOINT_REVISIONS, sort_keys=True).encode()
).hexdigest()[:16]


def pinned_directory(root: Path) -> Path:
    """Where the pinned snapshot lives under ACE-Step's checkpoint root."""
    return root / f"pinned-{CHECKPOINT_SET}"


def _components(dit_model: str, lm_model: str | None) -> tuple[list[str], list[str]]:
    requested = [name for name in (dit_model, lm_model) if name]
    extra = [name for name in requested if name not in _MAIN_COMPONENTS]
    return [*_MAIN_COMPONENTS, *extra], extra


def missing_pinned_components(root: Path, dit_model: str, lm_model: str | None) -> list[str]:
    """The components a local render would load that have no weights on disk yet.

    The same rule the render applies after fetching, so a check that reports nothing
    missing here is one a render will not fail on.
    """
    directory = pinned_directory(root)
    names, _extra = _components(dit_model, lm_model)
    return [
        name
        for name in names
        if not any((directory / name / filename).is_file() for filename in _WEIGHT_FILES)
    ]


@contextmanager
def pinned_checkpoints(root: Path, dit_model: str, lm_model: str | None) -> Iterator[Path]:
    """Download only immutable revisions and point ACE-Step at their complete local tree.

    The original cache stays untouched. Download errors propagate before either handler
    starts, and a partial cache is refused rather than letting upstream fetch latest.
    """
    _names, extra = _components(dit_model, lm_model)
    for name in extra:
        if f"ACE-Step/{name}" not in CHECKPOINT_REVISIONS:
            raise ValueError(f"No pinned ACE-Step checkpoint for {name!r}")

    from huggingface_hub import snapshot_download

    directory = pinned_directory(root)
    downloads = [
        (MAIN_REPO, directory),
        *[(f"ACE-Step/{name}", directory / name) for name in extra],
    ]
    for repo, destination in downloads:
        snapshot_download(
            repo_id=repo, revision=CHECKPOINT_REVISIONS[repo], local_dir=str(destination)
        )
    if missing := missing_pinned_components(root, dit_model, lm_model):
        raise RuntimeError(f"Pinned ACE-Step snapshot is incomplete: {missing[0]}")

    previous = os.environ.get("ACESTEP_CHECKPOINTS_DIR")
    os.environ["ACESTEP_CHECKPOINTS_DIR"] = str(directory)
    try:
        yield directory
    finally:
        if previous is None:
            os.environ.pop("ACESTEP_CHECKPOINTS_DIR", None)
        else:
            os.environ["ACESTEP_CHECKPOINTS_DIR"] = previous
