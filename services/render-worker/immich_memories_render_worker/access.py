"""Restore the app's account-aware reads before the first metadata request."""

from immich_memories.api.access_clients import AccessBoundClient, AccessRoutes
from immich_memories.api.sync_client import SyncImmichClient
from immich_memories.config_models import ImmichConfig, ImmichConnection


def immich_config(request) -> ImmichConfig:
    access = request.immich
    return ImmichConfig(
        url=str(access.url),
        api_key=access.api_key.get_secret_value(),
        api_version=access.api_version,
        accounts={
            name: ImmichConnection(
                url=str(access.url),
                api_key=account.api_key.get_secret_value(),
                api_version=account.api_version,
            )
            for name, account in access.accounts.items()
        },
    )


def render_client(request) -> SyncImmichClient:
    config = immich_config(request)
    if not request.asset_accounts:
        return SyncImmichClient(config.url, config.api_key, api_version=config.api_version)
    routes = AccessRoutes()
    routes.pin({str(asset_id): name for asset_id, name in request.asset_accounts.items()})
    return AccessBoundClient(config, routes=routes)


def request_secrets(request) -> tuple[str, ...]:
    return tuple(
        account.api_key.get_secret_value()
        for account in (request.immich, *request.immich.accounts.values())
    )
