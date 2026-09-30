"""A photo intermediate uses a verified encoder and an explicit color contract."""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING

from immich_memories.processing.encoding_plan import (
    EncodingPlan,
    EncodingRequest,
    HdrMode,
    HdrTransfer,
    OutputCodec,
    resolve_encoding_plan,
)

if TYPE_CHECKING:
    from immich_memories.config_loader import Config

logger = logging.getLogger(__name__)


def photo_encoding_plan(
    config: Config | None = None, *, transfer: HdrTransfer = HdrTransfer.PQ
) -> EncodingPlan:
    """Preserve photo HDR, except where NAS hardware requires an SDR intermediate."""
    from immich_memories.processing.hardware import (
        HWAccelCapabilities,
        detect_hardware_acceleration,
    )

    enabled = config is None or config.hardware.enabled
    capabilities = (
        detect_hardware_acceleration(config.hardware.backend if config else "auto")
        if enabled
        else HWAccelCapabilities()
    )
    hdr = transfer is not HdrTransfer.NONE
    if (
        hdr
        and config is not None
        and config.tier == "nas"
        and capabilities.supports_h264_encode
        and not capabilities.supports_h265_encode
    ):
        logger.info("NAS photo preparation uses hardware H.264 with HDR-to-SDR tone mapping")
        hdr = False
    plan = resolve_encoding_plan(
        EncodingRequest(
            OutputCodec.H265 if hdr else OutputCodec.H264,
            HdrMode.HDR if hdr else HdrMode.SDR,
            enabled,
            "balanced",
            8 if hdr else 18,
            "mp4",
        ),
        capabilities,
        input_transfer=transfer,
    )
    if plan.encoder == "libx265":
        trc = "smpte2084" if transfer is HdrTransfer.PQ else "arib-std-b67"
        plan = replace(
            plan,
            encoder_args=(
                *plan.encoder_args,
                "-x265-params",
                f"hdr-opt=1:repeat-headers=1:colorprim=bt2020:transfer={trc}:colormatrix=bt2020nc",
            ),
        )
    return plan
