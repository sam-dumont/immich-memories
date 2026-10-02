"""Provider-agnostic authentication helpers; web/server.py applies them in its middleware."""

from __future__ import annotations

import ipaddress
import logging
import secrets
import threading
from collections import OrderedDict, deque
from collections.abc import Mapping, MutableMapping
from datetime import UTC, datetime, timedelta

from immich_memories.config_models_auth import AuthConfig

logger = logging.getLogger(__name__)

# ---------- brute-force rate limiter ----------

_MAX_ATTEMPTS = 5
_WINDOW_SECONDS = 600  # 10 minutes
# Past this many sources the least recently failed is forgotten, so a flood of addresses
# cannot grow the process without bound.
_MAX_TRACKED = 10_000
# A username that keeps failing waits 30 s, then 60 s, 120 s ... up to the whole window,
# however many addresses the guesses come from.
_USERNAME_BACKOFF_SECONDS = 30
# Failures from everywhere together: past this, every sign-in waits a minute.
_GLOBAL_MAX_FAILURES = 100
_GLOBAL_PAUSE_SECONDS = 60

# {bucket: [failure times]}, least recently failed first -- guarded by _rate_lock
_failed_attempts: OrderedDict[str, list[datetime]] = OrderedDict()
_username_failures: OrderedDict[str, list[datetime]] = OrderedDict()
_global_failures: deque[datetime] = deque(maxlen=_GLOBAL_MAX_FAILURES)
_global_pause: list[datetime] = []
_rate_lock = threading.Lock()


def _bucket(ip: str) -> str:
    """The limiter's key for an address: IPv6 clients share one per /64, as they hold one each."""
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return str(address.ipv4_mapped)
        return str(ipaddress.ip_network(f"{address}/64", strict=False))
    return str(address)


def _recent(entries: OrderedDict[str, list[datetime]], key: str, now: datetime) -> list[datetime]:
    cutoff = now.timestamp() - _WINDOW_SECONDS
    recent = [ts for ts in entries.get(key, []) if ts.timestamp() >= cutoff]
    if recent:
        entries[key] = recent
    else:
        entries.pop(key, None)
    return recent


def _remember(entries: OrderedDict[str, list[datetime]], key: str, now: datetime) -> None:
    cutoff = now.timestamp() - _WINDOW_SECONDS
    # Least recently failed first: the stale entries are all at the front.
    while entries and next(iter(entries.values()))[-1].timestamp() < cutoff:
        entries.popitem(last=False)
    entries.setdefault(key, []).append(now)
    entries.move_to_end(key)
    while len(entries) > _MAX_TRACKED:
        entries.popitem(last=False)


def record_failed_login(ip: str, username: str = "") -> None:
    """Record a failed sign-in from *ip* for *username*."""
    now = datetime.now(UTC)
    with _rate_lock:
        _remember(_failed_attempts, _bucket(ip), now)
        if username:
            _remember(_username_failures, username, now)
        cutoff = now.timestamp() - _WINDOW_SECONDS
        while _global_failures and _global_failures[0].timestamp() < cutoff:
            _global_failures.popleft()
        _global_failures.append(now)
        if len(_global_failures) >= _GLOBAL_MAX_FAILURES:
            _global_pause[:] = [now + timedelta(seconds=_GLOBAL_PAUSE_SECONDS)]


def _username_backing_off(username: str, now: datetime) -> bool:
    failures = _recent(_username_failures, username, now)
    if len(failures) < _MAX_ATTEMPTS:
        return False
    wait = min(_USERNAME_BACKOFF_SECONDS * 2 ** (len(failures) - _MAX_ATTEMPTS), _WINDOW_SECONDS)
    return now < failures[-1] + timedelta(seconds=wait)


def is_rate_limited(ip: str, username: str = "") -> bool:
    """Whether *ip* (its /64 for IPv6) or *username* has failed too often to try again yet."""
    now = datetime.now(UTC)
    with _rate_lock:
        if len(_recent(_failed_attempts, _bucket(ip), now)) >= _MAX_ATTEMPTS:
            return True
        return bool(username) and _username_backing_off(username, now)


def sign_in_paused() -> bool:
    """Whether failures from everywhere together have paused every sign-in for now."""
    with _rate_lock:
        return bool(_global_pause) and datetime.now(UTC) < _global_pause[0]


def reset_rate_limiter() -> None:
    """Clear all rate-limit state -- for tests only."""
    with _rate_lock:
        _failed_attempts.clear()
        _username_failures.clear()
        _global_failures.clear()
        _global_pause.clear()


# WHY: only what the sign-in page itself needs is public: the client's built assets, the fonts,
# and its labels. Pictures, films and every other /api/v1 route stay behind the session.
_BYPASS_PREFIXES = ("/app/_app/", "/static/fonts/")
_HEALTH_BYPASS_EXACT = frozenset({"/health", "/health/live", "/health/ready"})
_BYPASS_EXACT = (
    frozenset(
        {
            "/login",
            "/app/login",
            "/auth/login",
            "/logout",
            "/auth/callback",
            "/auth/authorize",
            "/api/v1/i18n",
            "/api/v1/session",
        }
    )
    | _HEALTH_BYPASS_EXACT
)


def is_health_probe_path(path: str) -> bool:
    """Return whether path is an exact operational health endpoint."""
    return path in _HEALTH_BYPASS_EXACT


def is_bypass_path(path: str) -> bool:
    """Check if a path should bypass authentication."""
    if path in _BYPASS_EXACT:
        return True
    return any(path.startswith(prefix) for prefix in _BYPASS_PREFIXES)


def verify_credentials(username: str, password: str, auth_config: AuthConfig) -> bool:
    """Check username/password against config using constant-time comparison.

    Both are compared as UTF-8 bytes with secrets.compare_digest, which refuses non-ASCII
    text: a typed "ü" is a wrong password, not a server error.
    """
    username_ok = _same_secret(username, auth_config.username)
    password_ok = _same_secret(password, auth_config.password)
    return username_ok and password_ok


def _same_secret(presented: str, configured: str) -> bool:
    return secrets.compare_digest(presented.encode("utf-8"), configured.encode("utf-8"))


# The HTTP trigger API. Not a bypass path: a caller without a valid token still
# has to be a logged-in session, which is what the auth middleware decides.
_TRIGGER_PREFIX = "/api/trigger"


def is_trigger_path(path: str) -> bool:
    """Whether a path belongs to the HTTP trigger API."""
    return path == _TRIGGER_PREFIX or path.startswith(f"{_TRIGGER_PREFIX}/")


def presented_trigger_token(headers: Mapping[str, str]) -> str:
    """The trigger token a caller offered, from either header the API accepts.

    `x-api-key` is what Immich's own API takes, so a workflow calling us looks
    like a workflow calling Immich; `Authorization: Bearer` is what everything
    else reaches for. Anything else counts as no offer at all.
    """
    if api_key := headers.get("x-api-key", ""):
        return api_key
    scheme, _, value = headers.get("authorization", "").partition(" ")
    return value.strip() if scheme.lower() == "bearer" else ""


def trigger_token_matches(presented: str, configured: str) -> bool:
    """Constant-time comparison that refuses an unset token.

    Without the emptiness guard an operator who never set `server.trigger_token`
    would be authorizing every caller who also sends nothing.
    """
    if not configured or not presented:
        return False
    return _same_secret(presented, configured)


def trigger_token_authorizes(path: str, headers: Mapping[str, str], configured_token: str) -> bool:
    """Whether a trigger token lets this request skip the session check.

    The middleware asks this before the session check: a headless caller sends no
    session cookie, and a valid token is all it needs.
    """
    if not is_trigger_path(path):
        return False
    return trigger_token_matches(presented_trigger_token(headers), configured_token)


def _parse_proxy_networks(
    trusted_proxies: list[str],
) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """Parse proxy strings into network objects, skipping invalid entries."""
    networks = []
    for proxy in trusted_proxies:
        try:
            # ip_network handles both CIDR ("10.0.0.0/24") and single IPs ("10.0.0.1" -> /32)
            networks.append(ipaddress.ip_network(proxy, strict=False))
        except ValueError:
            continue
    return networks


def is_trusted_proxy(client_ip: str, trusted_proxies: list[str]) -> bool:
    """Check if client_ip matches any entry in trusted_proxies.

    Supports exact IP addresses and CIDR notation. Invalid entries are
    silently skipped. Returns False for invalid client IPs or empty lists.
    """
    if not trusted_proxies:
        return False

    try:
        addr = ipaddress.ip_address(client_ip)
    except ValueError:
        return False

    return any(addr in network for network in _parse_proxy_networks(trusted_proxies))


def set_session(
    session: MutableMapping[str, object],
    *,
    username: str,
    provider: str,
    email: str = "",
) -> None:
    """Populate session with authentication state."""
    session["authenticated"] = True
    session["username"] = username
    session["auth_provider"] = provider
    session["email"] = email
    session["authenticated_at"] = datetime.now(UTC).isoformat()


_SESSION_KEYS = (
    "authenticated",
    "username",
    "email",
    "auth_provider",
    "authenticated_at",
    "session_generation",
    "auth_fingerprint",
)


def clear_session(session: MutableMapping[str, object]) -> None:
    """Remove all authentication-related keys from the session."""
    for key in _SESSION_KEYS:
        session.pop(key, None)


def is_auth_enabled(auth_config: AuthConfig) -> bool:
    """Check whether authentication is enabled in config."""
    return auth_config.enabled
