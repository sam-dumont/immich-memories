"""Local-address policy for operator-configured service endpoints."""

from __future__ import annotations

import ipaddress
import os
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlsplit

if TYPE_CHECKING:
    from immich_memories.config_loader import Config


def validate_service_endpoints(config: Config) -> None:
    """Apply the same endpoint policy on config load and before saving settings."""
    endpoints = {
        "llm.base_url": config.llm.base_url,
        "editorial.preparation.caption_base_url": config.editorial.preparation.caption_base_url,
        "network.geocoding_url": config.network.geocoding_url,
        "musicgen.base_url": config.musicgen.base_url,
        "ace_step.api_url": config.ace_step.api_url,
        "render.worker_base_url": config.render.worker_base_url,
        "inference.facts_base_url": config.inference.facts_base_url,
    }
    if config.title_llm is not None:
        endpoints["title_llm.base_url"] = config.title_llm.base_url
    for key, value in endpoints.items():
        if value:
            _check_url(key, value)
    if config.notifications.urls:
        from apprise import Apprise

        for value in config.notifications.urls:
            if Apprise.instantiate(value, suppress_exceptions=True) is None:
                raise ValueError("notifications.urls needs supported Apprise URLs")
            _check_url("notifications.urls", value, notification=True)


def _check_url(key: str, value: str, *, notification: bool = False) -> None:
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        valid = notification or (parsed.scheme in {"http", "https"} and bool(host))
        if not notification:
            _ = parsed.port
    except ValueError:
        valid, host = False, None
    if not valid:
        raise ValueError(f"{key} needs an absolute HTTP(S) URL")
    if os.environ.get("IMMICH_MEMORIES_ALLOW_LINK_LOCAL_URLS", "").lower() in {"1", "true", "yes"}:
        return
    try:
        address = ipaddress.ip_address(unquote(host or "").split("%", 1)[0])
    except ValueError:
        return  # Literal-address guard only: no DNS lookup or redirect inspection.
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    if address.is_link_local:
        raise ValueError(
            f"{key} uses a link-local address; only the operator can allow it with "
            "IMMICH_MEMORIES_ALLOW_LINK_LOCAL_URLS=true"
        )
