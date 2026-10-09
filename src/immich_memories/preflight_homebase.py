"""Trip setup checks that do not query a library or expose its coordinates."""

from immich_memories.config import Config
from immich_memories.preflight import CheckResult, CheckStatus


def check_homebase(config: Config) -> CheckResult:
    try:
        config.trips.validate_homebase()
    except ValueError:
        return CheckResult(
            name="Homebase",
            status=CheckStatus.SKIPPED,
            message="Home coordinates not set; configure them to enable trips and seasons",
            details="Set trips.homebase_latitude and trips.homebase_longitude before finding trips; distance-based rules use this location.",
        )
    return CheckResult(
        name="Homebase", status=CheckStatus.OK, message="Home coordinates configured"
    )
