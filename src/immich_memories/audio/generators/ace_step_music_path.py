"""Whether a film's music comes from ACE-Step XL or from the bundled library.

Generated music is clearly better on the 4B XL turbo model than on the 2B one, so the app
generates only when the music will come from XL. Everything else plays a bundled track,
which was made with XL and listened to.

| mode | configured variant   | what decides                  | path                   |
|------|----------------------|-------------------------------|------------------------|
| lib  | auto                 | host memory                   | XL, else bundled       |
| lib  | an XL variant        | nothing: used as written      | XL                     |
| lib  | turbo / base / other | nothing: used as written      | 2B, with a warning     |
| api  | xl-turbo (asserted)  | the owner says the server runs XL | server's model     |
| api  | anything else        | the server's /health          | XL, else bundled       |

A server that does not say which model it runs (an old build, or nothing loaded yet) is
treated as not XL: a film then plays a track known to be good rather than one that may not
be. Setting ``model_variant: xl-turbo`` in API mode states that the server runs XL and
skips the question.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx

from immich_memories.audio.generators.ace_step_model_choice import (
    XL_VARIANT,
    HostMemory,
    is_auto,
    is_xl,
    measure_host,
    xl_fits,
)

logger = logging.getLogger(__name__)

_PROBE_TIMEOUT_SECONDS = 5.0
_PROBE_ATTEMPTS = 3
_PROBE_RETRY_SECONDS = 2.0
_WARNED: set[str] = set()


@dataclass(frozen=True, slots=True)
class MusicPath:
    """Which source a film's music takes, and why when it is not generated."""

    generate: bool
    reason: str = ""
    notice: str | None = None


def decide_music_path(
    *,
    mode: str,
    configured: str,
    host: HostMemory,
    server_model: str | None,
) -> MusicPath:
    """The decision table: ``mode`` is the mode that will run (``lib`` or ``api``)."""
    if mode == "api":
        return _api_path(configured, server_model)
    if is_auto(configured):
        if xl_fits(host):
            return MusicPath(True)
        return MusicPath(False, _host_reason(host))
    if is_xl(configured):
        return MusicPath(True)
    return MusicPath(
        True,
        notice=(
            f"ACE-Step model_variant '{configured}' loads a 2B model, which makes weaker music "
            "than XL. Set model_variant to 'auto' or 'xl-turbo' to use XL, or let films use the "
            "bundled library on a host without room for it."
        ),
    )


def _api_path(configured: str, server_model: str | None) -> MusicPath:
    if is_xl(configured):
        return MusicPath(True)
    if server_model is None:
        return MusicPath(
            False,
            "could not learn which model the ACE-Step server runs (unreachable, or no "
            "loaded_model on /health), so the bundled library plays; set model_variant to "
            "'xl-turbo' if it runs XL",
        )
    if is_xl(server_model):
        return MusicPath(True)
    return MusicPath(
        False,
        f"the ACE-Step server runs {server_model}, not an XL model; the bundled library plays",
    )


def _host_reason(host: HostMemory) -> str:
    if host.unified_gib is not None:
        have = f"{host.unified_gib:.0f} GB of unified memory"
    elif host.gpu_gib is not None:
        have = f"a {host.gpu_gib:.0f} GB GPU"
    else:
        have = "no GPU or unified memory it can use"
    return (
        f"this host has {have}; the XL model needs 64 GB of unified memory or a 16 GB GPU, "
        "so the bundled library plays"
    )


def local_check_profile(configured: str, host: HostMemory) -> tuple[MusicPath, str]:
    """What a local music check generates with: a lib-mode film's decision on this host.

    Returns that decision and the variant it loads: XL for ``auto``, else the configured one.
    A check that passes on any other model proves nothing about the films.
    """
    path = decide_music_path(mode="lib", configured=configured, host=host, server_model=None)
    return path, XL_VARIANT if is_auto(configured) else configured


def server_model(api_url: str) -> str | None:
    """The DiT model the ACE-Step API server reports on ``/health``; None when it cannot say."""
    for attempt in range(_PROBE_ATTEMPTS):
        try:
            response = httpx.get(f"{api_url.rstrip('/')}/health", timeout=_PROBE_TIMEOUT_SECONDS)
            response.raise_for_status()
            loaded = response.json().get("data", {}).get("loaded_model")
        except (httpx.HTTPError, ValueError, AttributeError, OSError) as exc:
            # A server busy decoding audio drops one probe; only a repeat means it cannot say.
            transient = isinstance(exc, httpx.TransportError) or (
                isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code >= 500
            )
            if transient and attempt + 1 < _PROBE_ATTEMPTS:
                time.sleep(_PROBE_RETRY_SECONDS)
                continue
            return None
        return loaded if isinstance(loaded, str) and loaded else None
    return None


def music_path_for(settings) -> MusicPath:
    """The path for a configured ACE-Step: measures this host, or asks the server."""
    from immich_memories.audio.generators.ace_step_isolated import isolated_python
    from immich_memories.audio.generators.ace_step_runtime import is_ace_step_importable

    runs_here = settings.mode == "lib" and (isolated_python() or is_ace_step_importable())
    if runs_here:
        path = decide_music_path(
            mode="lib",
            configured=settings.model_variant,
            host=measure_host(),
            server_model=None,
        )
    elif is_xl(settings.model_variant):
        path = decide_music_path(
            mode="api", configured=settings.model_variant, host=HostMemory(), server_model=None
        )
    else:
        path = decide_music_path(
            mode="api",
            configured=settings.model_variant,
            host=HostMemory(),
            server_model=server_model(settings.api_url),
        )
    if path.notice and path.notice not in _WARNED:
        _WARNED.add(path.notice)
        logger.warning(path.notice)
    return path


__all__ = [
    "XL_VARIANT",
    "MusicPath",
    "decide_music_path",
    "local_check_profile",
    "music_path_for",
    "server_model",
]
