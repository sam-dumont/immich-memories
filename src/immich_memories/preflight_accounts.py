"""Whether each extra Immich account under `immich.accounts` opens and proves who it is.

One result per account, named after it. The primary account is `check_immich`'s job. No
line holds a key or a server address: the account name is enough to find it in the config.
"""

from __future__ import annotations

from immich_memories.api.accounts import AccountUnavailable, open_accounts
from immich_memories.config_loader import Config
from immich_memories.preflight import CheckResult, CheckStatus


def check_extra_accounts(config: Config) -> list[CheckResult]:
    """Open every configured extra account on its own and report it; none configured, none."""
    results = []
    for name in sorted(config.immich.accounts):
        label = f"Immich account {name}"
        try:
            account = open_accounts(config.immich, [name])[name]
        except AccountUnavailable as error:
            results.append(CheckResult(label, CheckStatus.ERROR, "Connection failed", str(error)))
            continue
        account.client.close()
        user = account.user.name or account.user.email
        results.append(
            CheckResult(
                label,
                CheckStatus.OK,
                f"Connected as {user}",
                f"API: {account.api_version.value}",
            )
        )
    return results
