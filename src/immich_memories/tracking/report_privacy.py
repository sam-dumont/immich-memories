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

_UUID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE
)
# Any scheme, so postgresql://user:pw@host/db and redis://host go with http(s).
_URL = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s<>\"']+", re.IGNORECASE)
_IPV4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?(?![\w.])")
# WHY the lookahead: without "::" or all eight groups, "12:30:45" would read as an address.
_IPV6 = re.compile(
    r"(?<![\w:])(?=[0-9a-f:]*::|(?:[0-9a-f]{1,4}:){7})(?:[0-9a-f]{0,4}:){2,7}[0-9a-f]{0,4}(?![\w:])",
    re.IGNORECASE,
)
_HOST_PORT = re.compile(
    r"(?<![\w.\-/])(?=[\w.-]*[a-z])[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?:\d{2,5}(?!\w)", re.IGNORECASE
)
# Stack frames read "module.py:57"; they are the point of the report, not a host.
_SOURCE_FILE = re.compile(r"\.(?:py|pyi|js|ts|svelte):", re.IGNORECASE)
_PATH = re.compile(r"(?<![\w.:/~\\])(?:[A-Za-z]:[\\/]|~/|/(?=[\w.~-]))[^\s<>\"'(),;]*")
_COORDINATES = re.compile(r"(?<![\w.])-?\d{1,3}\.\d+\s*,\s*-?\d{1,3}\.\d+(?![\w.])")
_NAMED_COORDINATE = re.compile(
    r"\b(lat|lon|lng|latitude|longitude)(\s*[=:]\s*)-?\d+(?:\.\d+)?", re.IGNORECASE
)
# A term this short or without a letter or digit ("/", "Al") would hit ordinary words.
_MIN_TERM = 3


def _meaningful(term: str) -> bool:
    return len(term.strip()) >= _MIN_TERM and any(char.isalnum() for char in term)


def _host_port(match: re.Match[str]) -> str:
    return match[0] if _SOURCE_FILE.search(match[0]) else "[host]"


class ReportPrivacy:
    def __init__(self, *, terms: Iterable[str] = (), ids: Iterable[str] = ()) -> None:
        self._salt = secrets.token_bytes(32)
        self._ids = set(filter(None, ids))
        self._terms = set(filter(None, terms)) | {str(Path.home())}
        self._aliases: dict[str, str] = {}
        self._pattern: re.Pattern[str] | None = None
        self._replacements: dict[str, str] = {}
        self._compile()

    def include(self, *, ids: Iterable[str] = (), aliases: dict[str, str] | None = None) -> None:
        """Add a section's private vocabulary before any part of the report is sanitized."""
        self._ids.update(filter(None, ids))
        self._aliases.update(aliases or {})
        self._compile()

    def _compile(self) -> None:
        replacements = dict.fromkeys(self._terms, "[private]") | self._aliases
        replacements.update({identity: self.hash_id(identity) for identity in self._ids})
        replacements = {key: value for key, value in replacements.items() if _meaningful(key)}
        self._replacements = {key.lower(): value for key, value in replacements.items()}
        self._originals = replacements
        words = [re.escape(term) for term in sorted(replacements, key=len, reverse=True)]
        self._pattern = (
            re.compile(rf"(?<!\w)(?:{'|'.join(words)})(?!\w)", re.IGNORECASE) if words else None
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
        """Keep an identity joinable inside this report only; never export the salt."""
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
        if self._pattern is not None:
            value = self._pattern.sub(self._replace, value)
        return _UUID.sub(lambda match: self.hash_id(match[0]), value)

    def clean(self, value: Any) -> Any:
        """Sanitize values; keys are the report's own field names and stay readable."""
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {key: self.clean(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [self.clean(item) for item in value]
        return value
