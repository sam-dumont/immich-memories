"""The macOS Local Network permission, named when it is the likely reason Immich is unreachable (#2242).

macOS blocks a process's connections to addresses on the local network unless the program
responsible for it holds the Local Network permission. The connection then fails with
"No route to host" (errno 65), which reads like a network fault. Apple's own tools such as
curl are exempt, so `curl` reaching Immich while this program cannot is the tell.
"""

from __future__ import annotations

import ipaddress
import socket
import sys
from contextlib import suppress

# macOS's EHOSTUNREACH; the number differs on Linux, where this hint never applies.
_NO_ROUTE_TO_HOST_MACOS = 65


def _chain(exc: BaseException | None):
    """The exception and everything it was raised from, including an ExceptionGroup's members.

    anyio reports a refused address as "All connection attempts failed" with each attempt's
    own OSError inside a group, so the errno is not on the exception httpx hands us.
    """
    seen: set[int] = set()
    pending = [exc]
    while pending:
        current = pending.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        pending.extend([current.__cause__, current.__context__])
        pending.extend(getattr(current, "exceptions", ()))


def is_local_network(host: str) -> bool:
    # Loopback is never gated by macOS, nor is the internet.
    if host.lower() == "localhost":
        return False
    with suppress(ValueError):
        address = ipaddress.ip_address(host)
        return address.is_private and not address.is_loopback
    if "." not in host or host.endswith((".local", ".lan", ".home", ".internal")):
        return True
    try:
        resolved = socket.getaddrinfo(host, None)[0][4][0]
        return ipaddress.ip_address(resolved).is_private
    except (OSError, ValueError, IndexError):
        return False


def local_network_hint(exc: BaseException, host: str, *, platform: str | None = None) -> str | None:
    """How to grant the permission, when `exc` is macOS refusing a private address; else None."""
    if (platform or sys.platform) != "darwin":
        return None
    refused = any(
        isinstance(link, OSError) and link.errno == _NO_ROUTE_TO_HOST_MACOS for link in _chain(exc)
    )
    if not refused or not is_local_network(host):
        return None
    return (
        "macOS most likely blocked this program from reaching your local network. The permission "
        "belongs to the Python that runs immich-memories, not to Terminal: allow it in "
        "System Settings > Privacy & Security > Local Network. For a scheduled run, "
        "`immich-memories auto install` checks it and names the Python to allow"
    )
