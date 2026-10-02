"""Report ignored configuration names without configuration values."""

from immich_memories.config import Config
from immich_memories.preflight import CheckResult, CheckStatus


def check_unknown_config_keys(config: Config) -> list[CheckResult]:
    return [
        CheckResult(
            name="Configuration", status=CheckStatus.WARNING, message=f"Ignored unknown key: {key}"
        )
        for key in config.unknown_keys
    ]
