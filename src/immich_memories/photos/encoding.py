"""A photo intermediate uses a verified encoder and an explicit color contract."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from immich_memories.processing.encoding_plan import (
    EncodingPlan,
    EncodingRequest,
    HdrMode,
    HdrTransfer,
    OutputCodec,
    intermediate_encoding_plan,
    resolve_encoding_plan,
    resolve_output_selection,
)

if TYPE_CHECKING:
    from immich_memories.config.loader import Config
    from immich_memories.processing.hardware import HWAccelCapabilities

logger = logging.getLogger(__name__)


def photo_encoding_plan(
    config: Config | None = None,
    *,
    transfer: HdrTransfer = HdrTransfer.NONE,
    capabilities: HWAccelCapabilities | None = None,
    format_override: str | None = None,
) -> EncodingPlan:
    """Preserve source HDR only when the requested film can carry it."""
    from immich_memories.processing.hardware import (
        HWAccelCapabilities,
        detect_hardware_acceleration,
    )

    enabled = config is None or config.hardware.enabled
    if capabilities is None:
        capabilities = (
            detect_hardware_acceleration(config.hardware.backend if config else "auto")
            if enabled
            else HWAccelCapabilities()
        )
    hdr = _keeps_hdr(config, capabilities, transfer, format_override)
    from immich_memories.processing.hdr_utilities import quality_encoder_preset

    preset = (
        quality_encoder_preset(config.output.quality, config.hardware.encoder_preset)
        if config is not None
        else "balanced"
    )
    plan = resolve_encoding_plan(
        EncodingRequest(
            OutputCodec.H265 if hdr else OutputCodec.H264,
            HdrMode.HDR if hdr else HdrMode.SDR,
            enabled,
            preset,
            8 if hdr else 18,
            "mp4",
            codec_policy="strict",
        ),
        capabilities,
        input_transfer=transfer,
    )
    # The film decodes the move again, so it is encoded as an intermediate (#2709).
    return intermediate_encoding_plan(plan)


def _keeps_hdr(
    config: Config | None,
    capabilities: HWAccelCapabilities,
    transfer: HdrTransfer,
    format_override: str | None,
) -> bool:
    """Apply the film's HDR policy before choosing the photo's encoder."""
    enabled = config is None or config.hardware.enabled
    hdr = transfer is not HdrTransfer.NONE
    if config is not None:
        output = resolve_output_selection(
            config_codec=config.output.codec,
            config_container=config.output.format,
            format_override=format_override,
        )
        hdr = hdr and output.codec is OutputCodec.H265 and config.output.hdr_mode is not HdrMode.SDR
    if (
        hdr
        and enabled
        and config is not None
        and config.output.hdr_mode is HdrMode.AUTO
        and config.output.codec_policy == "prefer_hardware"
        and config.tier == "basic"
        and capabilities.supports_h264_encode
        and not capabilities.supports_h265_encode
    ):
        logger.info("NAS photo preparation uses hardware H.264 with HDR-to-SDR tone mapping")
        hdr = False
    return hdr
