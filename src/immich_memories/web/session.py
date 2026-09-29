"""Who is signed in, so the client knows whether to show sign-in or sign-out."""

from __future__ import annotations

from fastapi import APIRouter, Request

from immich_memories.config import get_config
from immich_memories.web.auth import is_auth_enabled
from immich_memories.web.schemas import CaptionDefaults, SessionView

router = APIRouter(prefix="/api/v1", tags=["session"])


@router.get("/session", response_model=SessionView)
def session_view(request: Request) -> SessionView:
    """The provider the sign-in page offers and whether this browser is signed in."""
    config = get_config()
    auth = config.auth
    enabled = is_auth_enabled(auth)
    session = request.scope.get("session") or {}
    return SessionView(
        auth_enabled=enabled,
        provider=auth.provider if enabled else None,
        signed_in=bool(session.get("authenticated")) or not enabled,
        username=session.get("username"),
        button_text=auth.button_text if enabled and auth.provider == "oidc" else None,
        auto_launch=enabled and auth.provider == "oidc" and auth.auto_launch,
        demo_mode_offered=config.server.enable_demo_mode,
        music_preview_offered=config.musicgen.enabled or config.ace_step.enabled,
        captions=CaptionDefaults(
            add_date=config.defaults.add_date, add_place=config.defaults.add_place
        ),
    )
