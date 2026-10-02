"""Report inference capability without changing an explicitly requested selection tier."""

from immich_memories.config_compute import inference_acceleration
from immich_memories.config_loader import Config
from immich_memories.preflight import CheckResult, CheckStatus


def check_inference_compute(config: Config) -> CheckResult:
    """Inspect the existing inference health/device probe without loading model weights."""
    name = "Inference compute"
    if config.tier == "nas":
        return CheckResult(name, CheckStatus.SKIPPED, "NAS selection does not require a GPU")
    try:
        available, reason = inference_acceleration(config.inference)
    except ValueError as error:
        return CheckResult(
            name, CheckStatus.ERROR, "Required inference service could not be verified", str(error)
        )
    if available:
        return CheckResult(name, CheckStatus.OK, "Inference GPU is available", reason)
    return CheckResult(
        name,
        CheckStatus.WARNING,
        f"No verified inference GPU for requested {config.tier} tier",
        f"{reason}. Check the CUDA image/device override or local Metal runtime; the requested tier is unchanged.",
    )
