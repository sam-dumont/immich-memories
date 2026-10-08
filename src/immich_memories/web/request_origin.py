"""Browser write-origin checks shared by the request middleware and sign-out."""

from collections.abc import Mapping
from urllib.parse import urlsplit

from immich_memories.config_loader import Config

_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_CHECKED_PREFIXES = ("/api/", "/auth/")


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
    if method not in _UNSAFE_METHODS or (
        path != "/logout" and not path.startswith(_CHECKED_PREFIXES)
    ):
        return False
    return cross_site_request(headers, config)


def cross_site_request(headers: Mapping[str, str], config: Config) -> bool:
    """Whether a browser on another site sent this request, write or read.

    A read carries nothing back to the sending page, so this is not a secrecy check:
    it exists so a visited page cannot make this server do expensive work behind a
    top-level navigation, the way it could with `?refresh=true`."""
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
