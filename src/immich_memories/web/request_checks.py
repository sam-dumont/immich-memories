"""Which requests reach the app at all: the Host they name, and where a write comes from.

A pure ASGI middleware around everything else. With authentication off, only a request
naming a local or explicitly allowed host is answered, so a page on another site cannot
rebind its own name to this server and read it. A browser write (POST, PUT, PATCH, DELETE)
under /api or /auth that another site started is refused, whatever the auth mode. Every
response says it may not be framed, and everything the app's own pages load is the app's
own origin. Writes carry at most a few MiB unless a route says otherwise, so an anonymous
oversized body is refused before it is ever buffered.
"""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import logging
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from urllib.parse import urlsplit

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from immich_memories.config_loader import Config
from immich_memories.config_models_server import WILDCARD_HOST
from immich_memories.web.job_routes import MAX_MUSIC_UPLOAD_BYTES
from immich_memories.web.request_origin import cross_site_write

logger = logging.getLogger(__name__)

# WHY: kubelet probes name the pod IP as Host; these two answer nothing a stranger can use.
_HOST_EXEMPT_PATHS = frozenset({"/health/live", "/health/ready"})
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "host.docker.internal"})
_UNBOUND_HOSTS = frozenset({"", WILDCARD_HOST, "::"})
_MISDIRECTED = (
    "This server does not answer to the host {host!r}. Add it to server.allowed_hosts, "
    "or enable authentication.\n"
)
_CROSS_SITE = "A write from another site is refused.\n"
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# Every write the API takes is a small JSON document; the one route that carries more
# (a soundtrack upload) names its own larger limit below. Without a default, any
# unauthenticated request could make the process buffer megabytes before a single
# credential was checked.
_DEFAULT_BODY_LIMIT = 4 * 1024 * 1024
# A soundtrack plus its multipart envelope; the route checks the file itself to the byte.
_BODY_LIMITS = {("POST", "/api/v1/music"): MAX_MUSIC_UPLOAD_BYTES + 64 * 1024}
_TOO_LARGE = "That request is too large.\n"
# Bounded so a stream of made-up names cannot grow it; past this, refusals log nothing new.
_LOGGED_HOSTS_MAX = 256


def _client_script_hashes() -> tuple[str, ...]:
    """Hashes of the built client's inline scripts, so the header permits exactly what
    the shipped bundle runs -- and a rebuilt bundle re-permits itself, no edit here.

    The bundle is built at package time (`make web-client`); in a bare source checkout
    there is nothing to hash and the policy simply allows no inline script.
    """
    try:
        html = (Path(__file__).parent / "client" / "index.html").read_text()
    except OSError:
        return ()
    return tuple(
        base64.b64encode(hashlib.sha256(script.encode()).digest()).decode("ascii")
        for script in re.findall(r"<script>(.*?)</script>", html, re.DOTALL)
    )


def _content_security_policy() -> bytes:
    """Same-origin everywhere, no plugin content, no foreign connections -- with the
    client's own inline scripts hashed in and inline styles allowed (Svelte components
    carry per-element styles)."""
    hashes = "".join(f" 'sha256-{digest}'" for digest in _client_script_hashes())
    return "; ".join(
        (
            "default-src 'self'",
            f"script-src 'self'{hashes}",
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data: blob:",
            "media-src 'self' blob:",
            "font-src 'self'",
            "object-src 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            "connect-src 'self'",
            "frame-ancestors 'none'",
        )
    ).encode()


_FRAMING = [
    (b"x-frame-options", b"DENY"),
    (b"content-security-policy", _content_security_policy()),
]


def _limit_for(method: str, path: str) -> int | None:
    """The most body bytes this request may carry, or None when it carries none.

    A route-specific limit wins (a soundtrack upload); otherwise every write under
    /api or /auth gets the default, so the pre-auth routes (`/auth/login` above all)
    cannot be used as an unauthenticated memory sink. Reads and pages take no body."""
    if (method, path) in _BODY_LIMITS:
        return _BODY_LIMITS[(method, path)]
    if method in _UNSAFE_METHODS and (path.startswith(("/api/", "/auth/")) or path == "/logout"):
        return _DEFAULT_BODY_LIMIT
    return None


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
    """Whether the server answers a request naming this host (already passed through `host_name`).

    With authentication on and no allow-list, the server answers any host -- unless the
    operator wrote the public URL, which is then the one host the sign-in redirect
    trusts, so a request naming another host is refused rather than shaping the OIDC
    redirect_uri."""
    if _local(name):
        return True
    allowed = {host_name(entry) for entry in config.server.allowed_hosts if entry.strip()}
    # The operator wrote the public URL too; an allow-list must not shut out its own sign-in.
    if public := urlsplit(config.auth.public_url).hostname:
        allowed.add(public)
    if config.auth.enabled and not allowed:
        return True
    if not config.auth.enabled and config.server.host not in _UNBOUND_HOSTS:
        allowed.add(host_name(config.server.host))
    return bool(name) and name in allowed


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
        limit = _limit_for(scope["method"], scope["path"])
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
    except* _BodyTooLarge:
        # ASGI task groups can wrap the overflow; suppress() only handles that on Python 3.12+.
        overflow = True
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
