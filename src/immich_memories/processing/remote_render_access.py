"""Transport only the account routes and credentials needed by the selected cut."""

from immich_memories.api.access_clients import AccessBoundClient
from immich_memories.config_models import PRIMARY_ACCOUNT
from immich_memories.processing.live_material import LiveRenderMaterial


def render_access(params, clips: list[dict]) -> dict:
    routes: dict[str, str] = {}
    client = params.client
    for source, chosen in zip(params.clips, clips, strict=True):
        owner = source.asset.access_accounts[0] if source.asset.access_accounts else None
        for asset_id in _source_ids(source.asset, chosen):
            account = (
                client.routes.account_of(asset_id)
                if isinstance(client, AccessBoundClient)
                else None
            ) or owner
            if account is not None:
                routes[asset_id] = account
    immich = params.config.immich
    accounts = {}
    for name in sorted(set(routes.values()) - {PRIMARY_ACCOUNT}):
        connection = immich.accounts.get(name)
        if connection is None:
            raise ValueError(f"Render account {name!r} is not configured")
        if connection.url.rstrip("/") != immich.url.rstrip("/"):
            raise ValueError("Render worker accounts must use the configured Immich server")
        accounts[name] = {
            "api_key": connection.api_key,
            "api_version": connection.api_version.value,
        }
    return {
        "immich": {
            "url": immich.url,
            "api_key": immich.api_key,
            "api_version": immich.api_version.value,
            "accounts": accounts,
        },
        "asset_accounts": routes,
    }


def _source_ids(asset, chosen: dict) -> list[str]:
    ids = [asset.id]
    if asset.live_photo_video_id:
        ids.append(asset.live_photo_video_id)
    if chosen["live"] is not None:
        material = LiveRenderMaterial.from_dict(chosen["live"]["material"])
        ids.extend([*material.still_ids, *material.video_ids])
    return ids
