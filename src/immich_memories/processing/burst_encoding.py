"""The encoding contract for a merged Live Photo burst.

The merge runs at download time, before the run's own EncodingPlan exists. Its
plan keeps the burst's transfer and makes the merge lossless, so the film's own
encode is the only lossy step a Live Photo takes (#2692): NVENC's lossless mode
where the machine has it, x264 everywhere else.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from immich_memories.processing.encoding_plan import (
    EncodingPlan,
    EncodingRequest,
    HdrMode,
    HdrTransfer,
    OutputCodec,
    lossless_encoding_plan,
    resolve_encoding_plan,
)
from immich_memories.processing.hardware import HWAccelCapabilities
from immich_memories.processing.hardware_detection import detect_hardware_acceleration

if TYPE_CHECKING:
    from immich_memories.config.loader import Config


def burst_capabilities(hardware_enabled: bool, config: Config | None) -> HWAccelCapabilities:
    """The hardware a merge may decode and encode with: none when hardware is off."""
    if not hardware_enabled or (config is not None and not config.hardware.enabled):
        return HWAccelCapabilities()
    return detect_hardware_acceleration(config.hardware.backend if config else "auto")


def burst_encoding_plan(
    *,
    is_hdr: bool,
    hardware_enabled: bool = True,
    config: Config | None = None,
    input_transfer: HdrTransfer | None = None,
) -> EncodingPlan:
    """The encoding contract for a merged burst: lossless, in the transfer it keeps.

    The source transfer survives preparation unless NAS hardware needs H.264.
    That case explicitly tone-maps to SDR. Certified caches bind the tier and
    hardware settings, so their intermediates cannot cross this policy boundary.
    """
    hardware_enabled = hardware_enabled and (config is None or config.hardware.enabled)
    capabilities = burst_capabilities(hardware_enabled, config)
    nas = config is not None and config.tier == "basic"
    preserve_hdr = is_hdr and not (
        nas and capabilities.supports_h264_encode and not capabilities.supports_h265_encode
    )
    request = EncodingRequest(
        codec=OutputCodec.H265 if preserve_hdr else OutputCodec.H264,
        hdr_mode=HdrMode.HDR if preserve_hdr else HdrMode.SDR,
        hardware_enabled=hardware_enabled,
        # The plan only decides the codec and transfer: the merge itself is lossless.
        preset="fast",
        crf=0,
        container="mp4",
        # NAS preparation chooses a codec its verified hardware can encode.
        codec_policy="prefer_hardware" if nas else "strict",
    )
    plan = resolve_encoding_plan(
        request, capabilities, input_has_hdr=is_hdr, input_transfer=input_transfer
    )
    # WHY (#2692): the film decodes the merge and encodes it again, so a lossy merge
    # was a second generation; its film encode is now the only lossy step.
    return lossless_encoding_plan(plan)


def append_encoding_args(cmd: list[str], plan: EncodingPlan, has_audio: bool, output: Path) -> None:
    """Append video/audio codec arguments to the FFmpeg command.

    Shares ``encoder_args_for_plan`` with the assembler rather than restating
    the codec/pixel-format/colour-tag rules, which is how the two drifted apart
    in the first place.
    """
    from immich_memories.processing.clip_encoder import encoder_args_for_plan

    cmd.extend(encoder_args_for_plan(plan))

    if has_audio:
        cmd.extend(["-c:a", "aac"])

    cmd.append(str(output))
