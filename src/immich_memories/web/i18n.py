"""The interface catalogue for the web client, the same `ui.po` the server pages use."""

from __future__ import annotations

import unicodedata
from functools import lru_cache
from typing import Annotated

from babel.messages.pofile import read_po
from fastapi import APIRouter, Header, Query

from immich_memories.i18n import LOCALES_DIR, SUPPORTED_LOCALES, babel_locale, resolve_ui_locale
from immich_memories.web.schemas import Language, Messages

router = APIRouter(prefix="/api/v1/i18n", tags=["i18n"])


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
    return Messages(locale=locale, messages=_catalogue(locale), languages=_languages())


@lru_cache(maxsize=1)
def _languages() -> list[Language]:
    named = []
    for code in SUPPORTED_LOCALES:
        name = babel_locale(code).get_display_name(code.replace("-", "_")) or code
        named.append(Language(code=code, name=name[:1].upper() + name[1:]))
    return sorted(named, key=_picker_order)


def _picker_order(language: Language) -> tuple[bool, str]:
    """By the language's own name as pickers list them: accents folded, Latin scripts first."""
    folded = "".join(
        c for c in unicodedata.normalize("NFKD", language.name) if not unicodedata.combining(c)
    ).casefold()
    return (not folded[:1].isascii(), folded)
