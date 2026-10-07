"""macOS says "No route to host" when the Local Network permission is missing (#2242)."""

from __future__ import annotations

import errno
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from immich_memories.api.immich import ImmichAPIError, ImmichClient
from immich_memories.api.local_network import local_network_hint


def _refused(code: int = 65) -> httpx.ConnectError:
    error = httpx.ConnectError("All connection attempts failed")
    error.__cause__ = OSError(code, "No route to host")
    return error


def test_a_private_address_refused_with_no_route_on_macos_names_the_permission():
    hint = local_network_hint(_refused(), "192.168.1.20", platform="darwin")

    assert hint is not None
    assert "Local Network" in hint
    assert "System Settings > Privacy & Security > Local Network" in hint


@pytest.mark.parametrize(
    ("exc", "host", "platform"),
    [
        pytest.param(_refused(), "192.168.1.20", "linux", id="not-macos"),
        pytest.param(_refused(), "93.184.216.34", "darwin", id="public-address"),
        pytest.param(_refused(errno.ECONNREFUSED), "192.168.1.20", "darwin", id="other-errno"),
        pytest.param(httpx.ConnectError("x"), "192.168.1.20", "darwin", id="no-os-error"),
    ],
)
def test_nothing_else_gets_the_hint(exc, host, platform):
    assert local_network_hint(exc, host, platform=platform) is None


def test_the_errno_inside_an_exception_group_is_found():
    """anyio wraps each address's failure in a group behind "All connection attempts failed"."""
    error = httpx.ConnectError("All connection attempts failed")
    error.__cause__ = OSError("All connection attempts failed")
    error.__cause__.__cause__ = ExceptionGroup("attempts", [OSError(65, "No route to host")])

    assert local_network_hint(error, "192.168.1.20", platform="darwin")


def test_a_name_with_no_dots_or_ending_in_local_counts_as_the_network():
    assert local_network_hint(_refused(), "nas", platform="darwin")
    assert local_network_hint(_refused(), "nas.local", platform="darwin")


@pytest.mark.asyncio
async def test_the_client_error_carries_the_hint_on_macos():
    client = ImmichClient("http://192.168.1.20:2283", "key-0123456789")
    client._client = AsyncMock()
    client._client.is_closed = False
    client._client.request = AsyncMock(side_effect=_refused())

    with (
        # WHY: the platform is the external fact the hint depends on.
        patch("immich_memories.api.local_network.sys.platform", "darwin"),
        patch("immich_memories.api.immich.asyncio.sleep", new_callable=AsyncMock),
        pytest.raises(ImmichAPIError) as raised,
    ):
        await client._request("GET", "/test")

    assert "Local Network" in str(raised.value)
    assert "192.168.1.20:2283" in str(raised.value)
