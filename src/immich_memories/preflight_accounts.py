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
    return [*results, *check_native_sharing(config)]


def check_native_sharing(config: Config) -> list[CheckResult]:
    """Explain native discovery separately from owner-key authentication."""
    if not config.immich.native_sharing:
        return []
    from immich_memories.api.access_clients import AccessBoundClient
    from immich_memories.api.compatibility import UnsupportedImmichVersion
    from immich_memories.api.immich import ImmichAPIError
    from immich_memories.security import sanitize_error_message

    label = "Immich native sharing"
    try:
        client = AccessBoundClient(config.immich)
        with client:
            native = client.native_people(("primary", *config.immich.accounts))
    except (AccountUnavailable, UnsupportedImmichVersion, ImmichAPIError, OSError) as error:
        detail = sanitize_error_message(str(error))
        for connection in (config.immich, *config.immich.accounts.values()):
            if connection.api_key:
                detail = detail.replace(connection.api_key, "***")
        return [CheckResult(label, CheckStatus.ERROR, "Discovery failed", detail)]
    if native is None:
        return [
            CheckResult(
                label,
                CheckStatus.WARNING,
                "Needs Immich 3.2 or later",
                "Keeping owner reads and existing bindings.",
            )
        ]
    experimental = "people" in native.modes.values()
    return [
        CheckResult(
            label,
            CheckStatus.WARNING if experimental else CheckStatus.OK,
            "Experimental 3.3 people sharing" if experimental else "Native identities available",
            "Selected owner keys remain required for favourites and complete libraries. Person access is checked for each requested identity; it does not grant asset access.",
        )
    ]
