"""The interface catalogue for the web client, the same `ui.po` the server pages use."""

from __future__ import annotations

import gettext
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated

from babel.messages.pofile import read_po
from fastapi import APIRouter, Header, Query

from immich_memories.i18n import LOCALES_DIR, SUPPORTED_LOCALES, babel_locale, resolve_ui_locale
from immich_memories.web.schemas import Language, Messages

router = APIRouter(prefix="/api/v1/i18n", tags=["i18n"])


# Counts that between them meet every plural rule CLDR and gettext write for these languages.
_SAMPLE_COUNTS = (*range(0, 200), 1_000_000)


@dataclass(frozen=True)
class _UiCatalogue:
    messages: dict[str, str]
    # A counted label's forms, keyed by its singular, in the catalogue's order.
    plurals: dict[str, list[str]]
    # The CLDR plural category each form stands for, so the browser's rules can pick one.
    plural_forms: list[str]


@lru_cache(maxsize=16)
def _catalogue(locale: str) -> _UiCatalogue:
    path = LOCALES_DIR / locale.replace("-", "_") / "LC_MESSAGES" / "ui.po"
    if not path.is_file():
        return _UiCatalogue({}, {}, ["one", "other"])
    with path.open("rb") as handle:
        catalogue = read_po(handle, locale=locale.replace("-", "_"))
    messages: dict[str, str] = {}
    plurals: dict[str, list[str]] = {}
    for entry in catalogue:
        if not entry.id or not entry.string:
            continue
        if isinstance(entry.id, tuple):
            plurals[entry.id[0]] = list(entry.string)
        else:
            messages[str(entry.id)] = str(entry.string)
    return _UiCatalogue(messages, plurals, _plural_categories(catalogue.plural_expr, locale))


def _plural_categories(plural_expr: str, locale: str) -> list[str]:
    """Name each gettext form by the CLDR category of the first count that lands in it."""
    form_of = gettext.c2py(plural_expr)
    category_of = babel_locale(locale).plural_form
    named: dict[int, str] = {}
    for count in _SAMPLE_COUNTS:
        named.setdefault(form_of(count), category_of(count))
    return [named.get(form, "other") for form in range(max(named) + 1)]


@router.get("", response_model=Messages)
def messages(
    accept_language: Annotated[str, Header()] = "",
    preference: Annotated[str, Query()] = "auto",
) -> Messages:
    """The browser's language, or the one the viewer chose; a missing string falls back to English."""
    locale = resolve_ui_locale(accept_language, preference=preference)
    catalogue = _catalogue(locale)
    return Messages(
        locale=locale,
        messages=catalogue.messages,
        plurals=catalogue.plurals,
        plural_forms=catalogue.plural_forms,
        languages=_languages(),
    )


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
