"""Whether this configured Immich key can complete film delivery."""

from collections.abc import Callable
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends

from immich_memories.api.immich import ImmichAPIError
from immich_memories.config_loader import Config
from immich_memories.web.dependencies import current_config
from immich_memories.web.schemas import RenderCapabilities

router = APIRouter(prefix="/api/v1/render", tags=["jobs"])


CapabilitiesReader = Callable[[], tuple[str, ...]]


def immich_render_capabilities(
    config: Annotated[Config, Depends(current_config)],
) -> CapabilitiesReader:
    def read() -> tuple[str, ...]:
        from immich_memories.api.sync_client import SyncImmichClient

        with SyncImmichClient(
            base_url=config.immich.url,
            api_key=config.immich.api_key,
            api_version=config.immich.api_version,
        ) as client:
            return client.get_key_capabilities().missing_upload

    return read


@router.get("/capabilities", response_model=RenderCapabilities)
def render_capabilities(
    read: Annotated[CapabilitiesReader, Depends(immich_render_capabilities)],
) -> RenderCapabilities:
    """Unavailable delivery never disables rendering or local download."""
    try:
        missing = read()
    except (ImmichAPIError, httpx.HTTPError):
        return RenderCapabilities(
            upload_available=False,
            missing_upload=[],
            upload_reason="Upload availability could not be checked. The film can still be rendered and downloaded.",
        )
    return RenderCapabilities(
        upload_available=not missing,
        missing_upload=list(missing),
        upload_reason="Upload unavailable: the key lacks " + ", ".join(missing)
        if missing
        else None,
    )
