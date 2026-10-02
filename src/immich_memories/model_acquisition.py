"""The explicit acquisition command's plan, also shown before browser consent."""

from dataclasses import dataclass
from pathlib import Path

from immich_memories.config_loader import Config
from immich_memories.config_models_llm import DEFAULT_LOCAL_MODEL
from immich_memories.laya_checkpoints import LAYA_ONNX_NAME
from immich_memories.local_inference import local_reader_paths
from immich_memories.pinned_models import (
    ENCODER,
    LAYA_AUDIENCE,
    LAYA_AUDIENCE_ONNX,
    LAYA_MAX_BYTES,
    MARQO_ONNX,
    MAX_MODEL_BYTES,
    READER_MAX_BYTES,
    READER_MODEL,
    READER_PROJECTOR,
    WORDNET,
    PinnedModel,
)


@dataclass(frozen=True)
class ModelAcquisition:
    artifact: PinnedModel
    destination: Path
    url: str
    size: str
    max_bytes: int = MAX_MODEL_BYTES
    cli_label: str = ""


def acquisition_plan(
    config: Config, *, detectors: bool | None = None, laya: bool = False
) -> list[ModelAcquisition]:
    """The CLI's configured artifacts, without importing downloaders or touching hosts."""
    # Sizes from immutable HF revision blob metadata and digest-pinned GitHub release assets.
    # Approximate decimal download sizes; the downloader keeps its existing safety bounds.
    plan = []
    if config.llm.runs_locally and config.llm.model == DEFAULT_LOCAL_MODEL:
        for pin, path in zip(
            (READER_MODEL, READER_PROJECTOR), local_reader_paths(config.llm), strict=True
        ):
            if pin == READER_PROJECTOR and config.llm.local_mmproj:
                continue
            plan.append(
                ModelAcquisition(
                    pin,
                    path,
                    pin.url,
                    "4.59 GB" if pin == READER_MODEL else "560 MB",
                    READER_MAX_BYTES,
                )
            )
    plan.extend(
        (
            ModelAcquisition(
                ENCODER,
                config.triage.encoder_path,
                config.triage.encoder_url,
                "88 MB",
                cli_label="encoder",
            ),
            ModelAcquisition(
                WORDNET,
                config.free_text.wordnet_path,
                config.free_text.wordnet_url,
                "11 MB",
                cli_label="wordnet",
            ),
        )
    )
    if laya or config.editorial.laya_audience:
        pin = (
            LAYA_AUDIENCE_ONNX
            if LAYA_ONNX_NAME
            in (
                config.editorial.laya_checkpoint_url.rsplit("/", 1)[-1],
                config.editorial.laya_checkpoint_path.name,
            )
            else LAYA_AUDIENCE
        )
        plan.append(
            ModelAcquisition(
                pin,
                config.editorial.laya_checkpoint_path,
                config.editorial.laya_checkpoint_url,
                "877 MB" if pin == LAYA_AUDIENCE_ONNX else "851 MB",
                LAYA_MAX_BYTES,
                cli_label="laya audience",
            )
        )
    include_detectors = config.editorial.detectors_enabled if detectors is None else detectors
    if include_detectors:
        prep = config.editorial.preparation
        plan.append(
            ModelAcquisition(
                MARQO_ONNX,
                prep.marqo_onnx_path,
                prep.marqo_onnx_url,
                "22.5 MB",
                cli_label="detector nsfw_marqo",
            )
        )
    return plan
