"""Which requests reach the app at all: the Host they name, and where a write comes from.

A pure ASGI middleware around everything else. With authentication off, only a request
naming a local or explicitly allowed host is answered, so a page on another site cannot
rebind its own name to this server and read it. A browser write (POST, PUT, PATCH, DELETE)
under /api or /auth that another site started is refused, whatever the auth mode. Every
response says it may not be framed.
"""

from __future__ import annotations

import ipaddress
import logging
from collections.abc import Callable, Mapping
from urllib.parse import urlsplit

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from immich_memories.config_loader import Config
from immich_memories.config_models_server import WILDCARD_HOST
from immich_memories.web.job_routes import MAX_MUSIC_UPLOAD_BYTES

logger = logging.getLogger(__name__)

# WHY: kubelet probes name the pod IP as Host; these two answer nothing a stranger can use.
_HOST_EXEMPT_PATHS = frozenset({"/health/live", "/health/ready"})
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "host.docker.internal"})
_UNBOUND_HOSTS = frozenset({"", WILDCARD_HOST, "::"})
_MISDIRECTED = (
    "This server does not answer to the host {host!r}. Add it to server.allowed_hosts, "
    "or enable authentication.\n"
)
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_CHECKED_PREFIXES = ("/api/", "/auth/")
_CROSS_SITE = "A write from another site is refused.\n"
_FRAMING = [
    (b"x-frame-options", b"DENY"),
    (b"content-security-policy", b"frame-ancestors 'none'"),
]
# A soundtrack plus its multipart envelope; the route checks the file itself to the byte.
_BODY_LIMITS = {("POST", "/api/v1/music"): MAX_MUSIC_UPLOAD_BYTES + 64 * 1024}
_TOO_LARGE = "That request is too large.\n"
# Bounded so a stream of made-up names cannot grow it; past this, refusals log nothing new.
_LOGGED_HOSTS_MAX = 256


def host_name(value: str) -> str:
    """The host part of a Host header or allow-list entry, lowercased, without port or brackets."""
    value = value.strip().lower()
    if value.startswith("["):
        return value[1:].split("]", 1)[0]
    if value.count(":") == 1:
        return value.split(":", 1)[0]
    return value


def _local(name: str) -> bool:
    if name in _LOCAL_HOSTS:
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


def host_allowed(name: str, config: Config) -> bool:
    """Whether the server answers a request naming this host (already passed through `host_name`)."""
    if _local(name):
        return True
    allowed = {host_name(entry) for entry in config.server.allowed_hosts if entry.strip()}
    if config.auth.enabled and not allowed:
        return True
    # The operator wrote the public URL too; an allow-list must not shut out its own sign-in.
    if public := urlsplit(config.auth.public_url).hostname:
        allowed.add(public)
    if not config.auth.enabled and config.server.host not in _UNBOUND_HOSTS:
        allowed.add(host_name(config.server.host))
    return bool(name) and name in allowed


def _origin_host(origin: str) -> str:
    """An Origin's host[:port], the port left out when it is the scheme's default."""
    parts = urlsplit(origin.strip().lower())
    default = {"http": 80, "https": 443}.get(parts.scheme)
    try:
        port = parts.port
    except ValueError:
        return origin
    host = f"[{parts.hostname}]" if parts.hostname and ":" in parts.hostname else parts.hostname
    return f"{host}:{port}" if port and port != default else str(host)


def _host_header(host: str, origin: str) -> str:
    host = host.strip().lower()
    default = {"http": ":80", "https": ":443"}.get(urlsplit(origin.strip().lower()).scheme, "")
    return host.removesuffix(default) if default else host


def cross_site_write(method: str, path: str, headers: Mapping[str, str], config: Config) -> bool:
    """Whether a browser on another site sent this write; a call without browser headers passes.

    `Sec-Fetch-Site` is set by the browser and no page can forge it, so `same-origin` and
    `none` pass outright (that also covers a proxy that rewrites Host). Without it, an
    `Origin` must name this Host or `auth.public_url`.
    """
    if method not in _UNSAFE_METHODS or not path.startswith(_CHECKED_PREFIXES):
        return False
    site = headers.get("sec-fetch-site", "").strip().lower()
    if site in ("cross-site", "same-site"):
        return True
    if site in ("same-origin", "none"):
        return False
    origin = headers.get("origin")
    if origin is None:
        return False
    named = _origin_host(origin)
    if named == _host_header(headers.get("host", ""), origin):
        return False
    public = config.auth.public_url
    return not (public and named == _origin_host(public))


def _headers(scope: Scope) -> dict[str, str]:
    return {key.decode("latin-1"): value.decode("latin-1") for key, value in scope["headers"]}


class RequestChecks:
    """The host and origin checks and the framing headers, for every HTTP request.

    `config` is called on each request, so a changed allow-list applies without a restart.
    """

    def __init__(self, app: ASGIApp, *, config: Callable[[], Config]) -> None:
        self.app = app
        self.config = config
        self._logged: set[str] = set()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        framed = _unframed(send)
        headers = _headers(scope)
        refusal = self._refusal(scope, headers)
        if refusal is not None:
            await _respond(framed, *refusal)
            return
        limit = _BODY_LIMITS.get((scope["method"], scope["path"]))
        if limit is None:
            await self.app(scope, receive, framed)
            return
        await _within(limit, headers, self.app, scope, receive, framed)

    def _refusal(self, scope: Scope, headers: Mapping[str, str]) -> tuple[int, str] | None:
        config = self.config()
        path = scope["path"]
        name = host_name(headers.get("host", ""))
        if path not in _HOST_EXEMPT_PATHS and not host_allowed(name, config):
            self._log_once(name)
            return 421, _MISDIRECTED.format(host=name)
        if cross_site_write(scope["method"], path, headers, config):
            return 403, _CROSS_SITE
        return None

    def _log_once(self, name: str) -> None:
        if name in self._logged or len(self._logged) >= _LOGGED_HOSTS_MAX:
            return
        self._logged.add(name)
        logger.warning(
            "Refused a request for host %r: not local and not in server.allowed_hosts", name
        )


class _BodyTooLarge(Exception):
    pass


def _announced(headers: Mapping[str, str]) -> int:
    try:
        return int(headers.get("content-length", "0"))
    except ValueError:
        return 0


async def _within(
    limit: int, headers: Mapping[str, str], app: ASGIApp, scope: Scope, receive: Receive, send: Send
) -> None:
    """Run the app with at most `limit` body bytes: refused up front when the length says
    more, cut off with 413 when the stream runs past it."""
    if _announced(headers) > limit:
        await _respond(send, 413, _TOO_LARGE)
        return
    received = 0
    started = overflow = False

    async def counted() -> Message:
        nonlocal received, overflow
        message = await receive()
        received += len(message.get("body", b""))
        if received > limit:
            overflow = True
            raise _BodyTooLarge
        return message

    async def sending(message: Message) -> None:
        nonlocal started
        # WHY: FastAPI turns an error while parsing a form into its own 400; past the limit
        # that answer is dropped and the 413 below goes instead.
        if overflow and not started:
            return
        started = started or message["type"] == "http.response.start"
        await send(message)

    try:
        await app(scope, counted, sending)
    except _BodyTooLarge:
        pass
    if overflow and not started:
        await _respond(send, 413, _TOO_LARGE)


def _unframed(send: Send) -> Send:
    async def sending(message: Message) -> None:
        if message["type"] == "http.response.start":
            message["headers"] = [*message.get("headers", []), *_FRAMING]
        await send(message)

    return sending


async def _respond(send: Send, status: int, body: str) -> None:
    start: Message = {
        "type": "http.response.start",
        "status": status,
        "headers": [(b"content-type", b"text/plain; charset=utf-8")],
    }
    await send(start)
    await send({"type": "http.response.body", "body": body.encode()})
