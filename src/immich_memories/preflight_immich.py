"""Connection and least-privilege diagnostics for the primary Immich API key."""

import httpx

from immich_memories.api.compatibility import UnsupportedImmichVersion
from immich_memories.api.permissions import (
    DELETE_PERMISSION,
    ApiKeyCapabilities,
    MissingReadPermissions,
)
from immich_memories.config_loader import Config
from immich_memories.preflight import CheckResult, CheckStatus
from immich_memories.security import sanitize_error_message


def check_immich(config: Config) -> CheckResult:
    """Check Immich server connection and API key validity.

    Args:
        config: Configuration to use.

    Returns:
        CheckResult with status and details.
    """
    if not config.immich.url:
        return CheckResult(
            name="Immich",
            status=CheckStatus.ERROR,
            message="URL not configured",
            details="Set immich.url in config or IMMICH_MEMORIES_IMMICH__URL env var",
        )

    if not config.immich.api_key:
        return CheckResult(
            name="Immich",
            status=CheckStatus.ERROR,
            message="API key not configured",
            details="Set immich.api_key in config or IMMICH_MEMORIES_IMMICH__API_KEY env var",
        )

    from immich_memories.api.immich import ImmichAPIError, SyncImmichClient

    try:
        with SyncImmichClient(
            base_url=config.immich.url,
            api_key=config.immich.api_key,
            api_version=config.immich.api_version,
        ) as client:
            resolved_version = client.get_api_version()
            capabilities = client.get_key_capabilities()
            capabilities.require_read()
            user = client.get_current_user()
            return _connected_result(
                config, user.name or user.email, resolved_version.value, capabilities
            )
    except MissingReadPermissions as error:
        return CheckResult(
            "Immich",
            CheckStatus.ERROR,
            "Required read permissions missing: " + ", ".join(error.missing),
            str(error),
        )
    except UnsupportedImmichVersion as e:
        safe_message = sanitize_error_message(str(e)).replace(config.immich.api_key, "***")
        return CheckResult(
            name="Immich",
            status=CheckStatus.ERROR,
            message="Unsupported Immich version",
            details=safe_message,
        )
    except ImmichAPIError as e:
        safe_message = sanitize_error_message(str(e)).replace(config.immich.api_key, "***")
        diagnostics = [safe_message]
        if e.status_code is not None:
            diagnostics.append(f"HTTP {e.status_code}")
        if e.correlation_id:
            safe_correlation = sanitize_error_message(e.correlation_id).replace(
                config.immich.api_key, "***"
            )
            diagnostics.append(f"Correlation ID: {safe_correlation}")
        return CheckResult(
            name="Immich",
            status=CheckStatus.ERROR,
            message="Connection failed",
            details="; ".join(diagnostics),
        )
    except (httpx.TimeoutException, httpx.HTTPStatusError, OSError) as e:
        return CheckResult(
            name="Immich",
            status=CheckStatus.ERROR,
            message="Connection failed",
            details=sanitize_error_message(str(e)).replace(config.immich.api_key, "***"),
        )


def _connected_result(
    config: Config, user: str, version: str, capabilities: ApiKeyCapabilities
) -> CheckResult:
    details = f"Server: {config.immich.url}"
    if config.immich.public_url:
        details += f"; links open {config.immich.link_base}"
    details += f"; API: {version}"
    warnings = []
    reasons = []
    if capabilities.is_all:
        warnings.append(
            "This key can delete or change your whole library; create a least-privilege key"
        )
        reasons.append("key can change your whole library")
        details += "; https://sam-dumont.github.io/immich-memories/docs/run/docker#the-api-key"
    if capabilities.missing_upload:
        warnings.append("Upload steps unavailable: " + ", ".join(capabilities.missing_upload))
        reasons.append("upload permissions not granted, films stay local")
    if not capabilities.allows(DELETE_PERMISSION):
        warnings.append("Previous version kept: the key lacks asset.delete")
        reasons.append("asset.delete not granted, previous versions are kept")
    return CheckResult(
        "Immich",
        CheckStatus.WARNING if warnings else CheckStatus.OK,
        "; ".join([f"Connected as {user}", *reasons]),
        details + ("; " + "; ".join(warnings) if warnings else ""),
    )
