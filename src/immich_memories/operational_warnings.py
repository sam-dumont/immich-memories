"""Operational warnings as a code plus params, worded where they are read.

A warning is stored as one string, so the run record, the report and every
reader written before this module keep working. A new warning is
`warn.<code>?name=value&...`; `render_warning` words it in a language from the
catalogue (`warning.<code>` in `messages.po`). Text that is not a coded warning,
every English string a store already holds, renders as it is.

Params are values the code itself knows (counts, permission names, a scrubbed
error), never anything read from the config: no URL, key, host or path.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl, quote, urlencode

from immich_memories.i18n import DEFAULT_LOCALE, film_text, resolve_film_locale

if TYPE_CHECKING:
    from immich_memories.config.loader import Config

_CODED = re.compile(r"^warn\.([a-z0-9_]+)(?:\?(.*))?$", re.DOTALL)
# What a list of warnings is joined with when it becomes one delivery reason.
JOINER = "; "


def coded(code: str, **params: object) -> str:
    """The stored form of one warning: `warn.<code>` and its params, percent-encoded."""
    query = urlencode({k: str(v) for k, v in params.items()}, quote_via=quote)
    return f"warn.{code}?{query}" if query else f"warn.{code}"


def _parse(text: str) -> tuple[str, dict[str, str]] | None:
    match = _CODED.match(text)
    if match is None:
        return None
    return match.group(1), dict(parse_qsl(match.group(2) or "", keep_blank_values=True))


def render_warning(text: str, locale: str = DEFAULT_LOCALE) -> str:
    """One warning, or several joined by "; ", in the language; old English text is unchanged."""
    pieces = text.split(JOINER)
    return JOINER.join(_render_one(piece, locale) for piece in pieces)


def _render_one(text: str, locale: str) -> str:
    parsed = _parse(text)
    if parsed is None:
        return text
    code, params = parsed
    nested = {key: render_warning(value, locale) for key, value in params.items()}
    key = f"warning.{code}"
    try:
        wording = film_text(key, locale, **nested)
    except (KeyError, IndexError, ValueError):
        return text
    return text if wording == key else wording


def render_warnings(texts: list[str], locale: str = DEFAULT_LOCALE) -> list[str]:
    """Each stored warning worded in the language."""
    return [render_warning(text, locale) for text in texts]


def scrub_warning(text: str, scrub: Callable[[str], str]) -> str:
    """Scrub a warning's free text. A coded warning is scrubbed value by value, so a secret
    the encoding changed ("https://host/" -> "https%3A%2F%2Fhost%2F") is still found."""
    pieces = text.split(JOINER)
    if not any(_parse(piece) for piece in pieces):
        return scrub(text)
    parts = []
    for piece in pieces:
        parsed = _parse(piece)
        if parsed is None:
            parts.append(scrub(piece))
        else:
            code, params = parsed
            parts.append(coded(code, **{k: scrub_warning(v, scrub) for k, v in params.items()}))
    return JOINER.join(parts)


def worded_for(config: Config, text: str) -> str:
    """The warning in the film's language, as the config sets it ("auto" follows the host)."""
    return render_warning(text, resolve_film_locale(config.title_screens.locale))
