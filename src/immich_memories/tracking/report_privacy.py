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
_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_PATH = re.compile(
    r"(?<!\w)(?:[A-Za-z]:[\\/]|/(?:Users|home|tmp|private|var|mnt|media|app|data)/)[^\s<>\"']+"
)


class ReportPrivacy:
    def __init__(self, *, terms: Iterable[str] = (), ids: Iterable[str] = ()) -> None:
        self._salt = secrets.token_bytes(32)
        self._ids = set(filter(None, ids))
        self._terms = set(filter(None, terms)) | {str(Path.home())}
        self._aliases: dict[str, str] = {}
        self._pattern: re.Pattern | None = None
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
        self._replacements = {key.casefold(): value for key, value in replacements.items() if key}
        words = [re.escape(term) for term in sorted(replacements, key=len, reverse=True) if term]
        self._pattern = re.compile("|".join(words), re.IGNORECASE) if words else None

    def hash_id(self, value: str) -> str:
        """Keep an identity joinable inside this report only; never export the salt."""
        return "id-" + hashlib.blake2s(value.encode(), key=self._salt, digest_size=8).hexdigest()

    def text(self, value: str) -> str:
        """Apply existing secret filtering before personal values, URLs and paths."""
        record = logging.LogRecord("report", logging.INFO, "", 0, value, (), None)
        SecretRedactionFilter().filter(record)
        value = _PATH.sub("[path]", _URL.sub("[url]", record.getMessage()))
        if self._pattern is not None:
            value = self._pattern.sub(lambda match: self._replacements[match[0].casefold()], value)
        return _UUID.sub(lambda match: self.hash_id(match[0]), value)

    def clean(self, value: Any) -> Any:
        """Sanitize keys too: model and stage labels may contain private text."""
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {self.text(str(key)): self.clean(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [self.clean(item) for item in value]
        return value
