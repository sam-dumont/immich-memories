"""The film's name as a person sees it: in Immich and on a web download.

The file on disk keeps its English name, which scripts read (`filename_builder.py`). This builds
the same name from the same parts with the film's language in it: the memory type as the
film-type list says it, the people's names as they are written. Only what is shown changes.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

if TYPE_CHECKING:
    from immich_memories.config.loader import Config

# Windows and most NAS shares refuse these in a name.
_UNSAFE = re.compile(r'[/\\:*?"<>|]')
# Filesystems cap a name at 255 bytes; a CJK letter takes three of them.
_MAX_NAME_BYTES = 200
_SEPARATOR = " "


def safe_display_name(text: str, *, max_bytes: int = _MAX_NAME_BYTES) -> str:
    """A name any filesystem and browser takes: no path or reserved characters, no control or
    invisible ones (a right-to-left override can fake an extension), whitespace collapsed, no
    leading or trailing dot, at most `max_bytes` of UTF-8. Letters of every script stay."""
    kept = []
    for char in unicodedata.normalize("NFC", text):
        category = unicodedata.category(char)
        if category == "Cc" or category in {"Zs", "Zl", "Zp"}:
            kept.append(" ")
        elif category[0] != "C":
            kept.append(char)
    folded = " ".join(_UNSAFE.sub(" ", "".join(kept)).split()).strip(" .")
    while len(folded.encode()) > max_bytes:
        folded = folded[:-1]
    return folded.rstrip(" .")


def shown_film_name(
    disk_name: str,
    *,
    memory_type: str | None,
    type_label: str | None,
    people: str | None,
    locale: str,
) -> str:
    """The disk name's own parts with the type and the people in the film's language.

    `camille_year_in_review_2024_a1b2c3d4.mp4` shows as `Camille Année en revue 2024 a1b2c3d4.mp4`.
    English, a custom file name and a name the builder did not make come back unchanged, and
    the recipe hash that ends a name always survives a cap.
    """
    stem, dot, suffix = disk_name.rpartition(".")
    if not dot or locale == "en" or not memory_type or not type_label:
        return disk_name
    album = re.fullmatch(r"album(?:_(?P<slug>.+))?", stem) if memory_type == "album" else None
    if album:
        slug = (album.group("slug") or "").replace("_", _SEPARATOR)
        head, tail = [type_label, slug], ""
    else:
        built = re.fullmatch(
            rf"(?P<who>.+?)_(?P<type>{re.escape(memory_type)}(?:_or)?)_(?P<rest>.+)", stem
        )
        if built is None:
            return disk_name
        head, tail = [people or "", type_label], built.group("rest").replace("_", _SEPARATOR)
    ending = f"{_SEPARATOR}{safe_display_name(tail)}" if tail else ""
    room = _MAX_NAME_BYTES - len(ending.encode()) - len(suffix.encode()) - 1
    name = safe_display_name(_SEPARATOR.join(p for p in head if p), max_bytes=max(room, 1))
    return f"{name}{ending}.{suffix}" if name else disk_name


def shown_film_name_for(
    config: Config,
    disk_name: str,
    *,
    memory_type: str | None,
    person_name: str | None,
    preset_params: Mapping[str, Any] | None = None,
) -> str:
    """`shown_film_name` for a film made under this config: its language, its cast."""
    from immich_memories.filename_builder import build_title_person_name
    from immich_memories.i18n import resolve_film_locale
    from immich_memories.operations.film_labelling import film_type_label

    locale = resolve_film_locale(config.title_screens.locale)
    params = dict(preset_params or {})
    return shown_film_name(
        disk_name,
        memory_type=memory_type,
        type_label=film_type_label(memory_type, params, locale),
        people=build_title_person_name(
            memory_type, params, person_name, use_first_name_only=False, locale=locale
        ),
        locale=locale,
    )


def content_disposition(shown: str, fallback: str) -> str:
    """An attachment header carrying the shown name (RFC 6266 `filename*`) and an ASCII
    `filename=` for clients that read only that one: the disk name, which is ASCII."""
    plain = safe_display_name(fallback.encode("ascii", "replace").decode().replace("?", "_"))
    plain = plain or "film.mp4"
    if shown == plain:
        return f'attachment; filename="{plain}"'
    return f"attachment; filename=\"{plain}\"; filename*=UTF-8''{quote(shown, safe='')}"
