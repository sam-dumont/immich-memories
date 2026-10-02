"""Sign-in checks: a weak basic-auth password is worth a warning before the UI serves it."""

from immich_memories.config import Config
from immich_memories.preflight import CheckResult, CheckStatus
from immich_memories.startup_checks import startup_warnings


def check_sign_in(config: Config) -> CheckResult:
    if not config.auth.enabled:
        return CheckResult(
            name="Sign-in", status=CheckStatus.SKIPPED, message="Authentication disabled"
        )
    if warnings := startup_warnings(config):
        return CheckResult(name="Sign-in", status=CheckStatus.WARNING, message=warnings[0])
    return CheckResult(
        name="Sign-in", status=CheckStatus.OK, message=f"{config.auth.provider} sign-in configured"
    )
