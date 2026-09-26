"""The interface catalogue for the web client, the same `ui.po` the server pages use."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from babel.messages.pofile import read_po
from fastapi import APIRouter, Header, Query
from pydantic import BaseModel

from immich_memories.i18n import LOCALES_DIR, resolve_ui_locale

router = APIRouter(prefix="/api/v1/i18n", tags=["i18n"])


class Messages(BaseModel):
    locale: str
    messages: dict[str, str]


@lru_cache(maxsize=16)
def _catalogue(locale: str) -> dict[str, str]:
    path = LOCALES_DIR / locale.replace("-", "_") / "LC_MESSAGES" / "ui.po"
    if not path.is_file():
        return {}
    with path.open("rb") as handle:
        catalogue = read_po(handle, locale=locale.replace("-", "_"))
    return {str(entry.id): str(entry.string) for entry in catalogue if entry.id and entry.string}


@router.get("", response_model=Messages)
def messages(
    accept_language: Annotated[str, Header()] = "",
    preference: Annotated[str, Query()] = "auto",
) -> Messages:
    """The browser's language, or the one the viewer chose; a missing string falls back to English."""
    locale = resolve_ui_locale(accept_language, preference=preference)
    return Messages(locale=locale, messages=_catalogue(locale))
