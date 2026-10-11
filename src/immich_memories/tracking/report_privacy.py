"""Report-local pseudonyms and redaction applied after fields have been selected."""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from immich_memories.logging_config import SecretRedactionFilter

# WHY lookarounds, not \b: logs name files after ids ("<id>_photo.mp4", "clip_<id>.mp4"), and
# "_" is a word character, so \b let an id glued to an underscore through unhashed (#2397).
_UUID = re.compile(
    r"(?<![0-9A-Za-z])[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?![0-9A-Za-z])",
    re.IGNORECASE,
)
# A private id ends where its alphabet does; "-" belongs to it, so "a-b" never half-matches
# inside the longer id "a-b-01".
_ID_EDGE_BEFORE, _ID_EDGE_AFTER = r"(?<![0-9A-Za-z-])", r"(?![0-9A-Za-z-])"
# A name or place ends at anything but a letter or digit, "_" included: "Kit_photo" names Kit,
# "Kitchen" does not.
_TERM_EDGE_BEFORE, _TERM_EDGE_AFTER = r"(?<![^\W_])", r"(?![^\W_])"
# The address, path and coordinate patterns below stop at letters and digits, never at "_":
# a log line glues them to file names ("tile_50.85,4.35.png") as often as to spaces, and a
# trailing dot ends a sentence or starts an extension, not another number (#2397).
# Any scheme, so postgresql://user:pw@host/db and redis://host go with http(s).
_URL = re.compile(r"(?<![0-9A-Za-z+.-])[a-z][a-z0-9+.-]*://[^\s<>\"']+", re.IGNORECASE)
_IPV4 = re.compile(r"(?<![0-9A-Za-z.])(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?(?![0-9A-Za-z]|\.\d)")
# WHY the lookahead: without "::" or all eight groups, "12:30:45" would read as an address.
_IPV6 = re.compile(
    r"(?<![\w:])(?=[0-9a-f:]*::|(?:[0-9a-f]{1,4}:){7})(?:[0-9a-f]{0,4}:){2,7}[0-9a-f]{0,4}(?![\w:])",
    re.IGNORECASE,
)
_HOST_PORT = re.compile(
    r"(?<![0-9A-Za-z.\-/])(?=[\w.-]*[a-z])[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?:\d{2,5}(?![0-9A-Za-z])",
    re.IGNORECASE,
)
# Stack frames read "module.py:57"; they are the point of the report, not a host.
_SOURCE_FILE = re.compile(r"\.(?:py|pyi|js|ts|svelte):", re.IGNORECASE)
_PATH = re.compile(r"(?<![0-9A-Za-z.:/~\\])(?:[A-Za-z]:[\\/]|~/|/(?=[\w.~-]))[^\s<>\"'(),;]*")
_COORDINATES = re.compile(
    r"(?<![0-9A-Za-z.])-?\d{1,3}\.\d+\s*,\s*-?\d{1,3}\.\d+(?![0-9A-Za-z]|\.\d)"
)
_NAMED_COORDINATE = re.compile(
    r"(?<![0-9A-Za-z])(lat|lon|lng|latitude|longitude)(\s*[=:]\s*)-?\d+(?:\.\d+)?", re.IGNORECASE
)
# One letter, or no letter or digit ("/", "A"), would hit ordinary text; a two-letter name
# ("Al", "Jo") is still a name, and whole-word matching keeps it off "Alarm".
_MIN_TERM = 2


def _meaningful(term: str) -> bool:
    return len(term.strip()) >= _MIN_TERM and any(char.isalnum() for char in term)


def _alternation(keys: list[str], before: str, after: str) -> re.Pattern[str] | None:
    """One case-blind pattern for `keys`, longest first so a key never half-matches a longer one."""
    if not keys:
        return None
    words = "|".join(re.escape(key) for key in sorted(keys, key=len, reverse=True))
    return re.compile(rf"{before}(?:{words}){after}", re.IGNORECASE)


def _host_port(match: re.Match[str]) -> str:
    return match[0] if _SOURCE_FILE.search(match[0]) else "[host]"


class ReportPrivacy:
    def __init__(self, *, terms: Iterable[str] = (), ids: Iterable[str] = ()) -> None:
        self._salt = secrets.token_bytes(32)
        self._ids = set(filter(None, ids))
        self._terms = set(filter(None, terms)) | {str(Path.home())}
        self._aliases: dict[str, str] = {}
        self._pattern: re.Pattern[str] | None = None
        self._id_pattern: re.Pattern[str] | None = None
        self._replacements: dict[str, str] = {}
        self._compile()

    def include(self, *, ids: Iterable[str] = (), aliases: dict[str, str] | None = None) -> None:
        """Add a section's private vocabulary before any part of the report is sanitized."""
        self._ids.update(filter(None, ids))
        self._aliases.update(aliases or {})
        self._compile()

    def _compile(self) -> None:
        terms = dict.fromkeys(self._terms, "[private]") | self._aliases
        ids = {identity: self.hash_id(identity) for identity in self._ids}
        replacements = {key: value for key, value in (terms | ids).items() if _meaningful(key)}
        self._replacements = {key.lower(): value for key, value in replacements.items()}
        self._originals = replacements
        self._pattern = _alternation(
            [key for key in replacements if key not in ids], _TERM_EDGE_BEFORE, _TERM_EDGE_AFTER
        )
        self._id_pattern = _alternation(
            [key for key in replacements if key in ids], _ID_EDGE_BEFORE, _ID_EDGE_AFTER
        )

    def _replace(self, match: re.Match[str]) -> str:
        found = match[0]
        if (value := self._replacements.get(found.lower())) is not None:
            return value
        # WHY: case folding can change a term's length ("İzmir"), so the lowered key misses;
        # ask the same case-insensitive rule which term this was.
        for term, value in self._originals.items():
            if re.fullmatch(re.escape(term), found, re.IGNORECASE):
                return value
        return "[private]"

    def hash_id(self, value: str) -> str:
        """Keep an identity joinable inside this report only; never export the salt.

        An Immich id is one id in any case, so it hashes the same wherever the report meets it.
        """
        if _UUID.fullmatch(value):
            value = value.lower()
        return "id-" + hashlib.blake2s(value.encode(), key=self._salt, digest_size=8).hexdigest()

    def text(self, value: str) -> str:
        """Secrets first, then addresses, paths and places, then personal words and IDs."""
        record = logging.LogRecord("report", logging.INFO, "", 0, value, (), None)
        SecretRedactionFilter().filter(record)
        value = _URL.sub("[url]", record.getMessage())
        value = _IPV6.sub("[host]", _IPV4.sub("[host]", value))
        value = _HOST_PORT.sub(_host_port, value)
        value = _PATH.sub("[path]", value)
        value = _NAMED_COORDINATE.sub(r"\1\2[location]", _COORDINATES.sub("[location]", value))
        if self._id_pattern is not None:
            value = self._id_pattern.sub(self._replace, value)
        if self._pattern is not None:
            value = self._pattern.sub(self._replace, value)
        return _UUID.sub(lambda match: self.hash_id(match[0]), value)

    def clean(self, value: Any) -> Any:
        """Sanitize keys and values; stage and model names can carry private words too."""
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            cleaned: dict[Any, Any] = {}
            for key, item in value.items():
                name = self.text(key) if isinstance(key, str) else key
                # WHY: two keys can redact to the same name; numbering keeps both values.
                unique, count = name, 1
                while unique in cleaned:
                    count += 1
                    unique = f"{name} ({count})"
                cleaned[unique] = self.clean(item)
            return cleaned
        if isinstance(value, (tuple, list)):
            return [self.clean(item) for item in value]
        return value
