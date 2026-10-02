"""What the web server refuses to start with, and what it only warns about.

A refusal is a setting that would let a stranger in: a session secret short enough to guess
(a forged cookie is a signed-in session), a trigger token anyone could try, or a
`FORWARDED_ALLOW_IPS` that lets every client name its own address to the login limiter and to
header auth. A warning is a choice that is weak but still the operator's to make.
"""

from __future__ import annotations

from collections.abc import Mapping

from immich_memories.config_loader import Config

MIN_SECRET_LENGTH = 32
MIN_PASSWORD_LENGTH = 12
_WEAK_WORDS = ("change-me", "changeme", "secret", "password", "example")
_GENERATE = "generate one with `openssl rand -hex 32`"


class StartupRefused(RuntimeError):
    """The configuration is unsafe to serve; the message says what to change."""


def weak_secret(value: str) -> bool:
    """Whether a secret is short enough to guess or carries a placeholder word."""
    lowered = value.lower()
    return len(value) < MIN_SECRET_LENGTH or any(word in lowered for word in _WEAK_WORDS)


def startup_refusals(config: Config, environ: Mapping[str, str], session_secret: str) -> list[str]:
    """Every reason not to serve this configuration, empty when it is safe to start."""
    refusals = []
    if weak_secret(session_secret):
        refusals.append(
            "IMMICH_MEMORIES_STORAGE_SECRET (or ~/.immich-memories/.storage_secret) signs every "
            f"session and is too weak: it needs {MIN_SECRET_LENGTH}+ random characters; {_GENERATE}"
        )
    if config.server.trigger_token and weak_secret(config.server.trigger_token):
        refusals.append(
            f"server.trigger_token is too weak: it needs {MIN_SECRET_LENGTH}+ random characters; "
            f"{_GENERATE}"
        )
    refusals.extend(_forwarding_refusals(config, environ.get("FORWARDED_ALLOW_IPS")))
    return refusals


def _forwarding_refusals(config: Config, forwarded_allow_ips: str | None) -> list[str]:
    if forwarded_allow_ips is None or not config.auth.enabled:
        return []
    if config.auth.provider == "header":
        return [
            "FORWARDED_ALLOW_IPS is set with auth.provider: header; header auth trusts the proxy "
            "by the address it connects from, so unset FORWARDED_ALLOW_IPS and list the proxy in "
            "auth.trusted_proxies only"
        ]
    if "*" in (entry.strip() for entry in forwarded_allow_ips.split(",")):
        return [
            "FORWARDED_ALLOW_IPS='*' lets clients choose their own address; "
            "list your proxy's address instead"
        ]
    return []


def startup_warnings(config: Config) -> list[str]:
    """Weak settings worth a line in the log and in preflight, but not a refusal."""
    auth = config.auth
    if auth.enabled and auth.provider == "basic" and len(auth.password) < MIN_PASSWORD_LENGTH:
        return [
            f"auth.password is shorter than {MIN_PASSWORD_LENGTH} characters; "
            "a longer one resists guessing far better"
        ]
    return []


def check_startup(config: Config, environ: Mapping[str, str], session_secret: str) -> list[str]:
    """Raise `StartupRefused` on any refusal; otherwise return the warnings to log."""
    if refusals := startup_refusals(config, environ, session_secret):
        raise StartupRefused("Not starting the UI: " + "; ".join(refusals))
    return startup_warnings(config)
