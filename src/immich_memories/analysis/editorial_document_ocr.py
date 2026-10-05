"""The run's per-asset OCR text reader, bounded to a cold year under an hour (#2062).

Split out of `editorial_runtime.py` (round 3): reading a personal document's OCR text is one
cohesive unit (version gate, bulk prefilter, memoisation), separate from the rest of that
module's production wiring.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Any, cast

import httpx

from immich_memories.analysis.editorial_carrier_eligibility import (
    DOCUMENT_TITLE_WORDS,
    PERSONAL_RECORD_FIELD_WORDS,
)
from immich_memories.api.accounts import AccountUnavailable
from immich_memories.api.immich import ImmichAPIError
from immich_memories.config_models import PRIMARY_ACCOUNT
from immich_memories.free_text.printed import ImmichPrintedText

logger = logging.getLogger(__name__)

# Immich's cheap, library-wide keyword search as a first pass: a personal document's own
# title or a field it prints. Built from the same words the content check reads
# (`editorial_carrier_eligibility.py`), so a word added there is searched here too and the
# two vocabularies can never drift apart (#2062 round 4). MRZ, Luhn and IBAN text cannot be
# keyword-searched this way; `document_ocr_port` reads those candidates' OCR directly,
# keyed off the frame head instead.
# A word search is wasted twice: "identiteitskaart" is both a field label and a title
# word, since Dutch ID cards print it both ways, so the combined tuple is deduplicated.
_OCR_PREFILTER_WORDS: tuple[str, ...] = tuple(
    dict.fromkeys(PERSONAL_RECORD_FIELD_WORDS + DOCUMENT_TITLE_WORDS)
)
_OCR_MIN_VERSION = (2, 2)


def _ocr_capable_reader(client: object) -> Callable[[str], str | None] | None:
    """`get_asset_ocr_text`, bound to `client`, once its server proves it's 2.2+.

    Anything that keeps this from being certain -- no method, no version, too old a server
    -- skips the signal outright rather than ask every candidate and fail the same way
    every time.
    """
    get_server_info = getattr(client, "get_server_info", None)
    get_text = getattr(client, "get_asset_ocr_text", None)
    if not callable(get_server_info) or not callable(get_text):
        return None
    try:
        info = get_server_info()
    except (ImmichAPIError, httpx.HTTPError, OSError) as exc:
        logger.warning(
            "Could not read Immich's server version; personal-document OCR is off: %s", exc
        )
        return None
    if (info.major, info.minor) < _OCR_MIN_VERSION:
        logger.info(
            "Immich %s predates per-asset OCR reads; personal-document OCR is off",
            info.version_string,
        )
        return None
    return cast(Callable[[str], "str | None"], get_text)


def _search_clients(client: object, accounts: Sequence[str]) -> list[object]:
    """Every account's own client worth searching: the primary (`client` itself, when it
    can search at all) plus each configured secondary -- `search_metadata` stays on the
    account that owns it, unlike `get_asset`/`get_asset_faces`, so a household's documents
    on a secondary account are only found by asking that account directly (#2062 round 4).
    """
    searchers: list[object] = []
    if callable(getattr(client, "search_metadata", None)):
        searchers.append(client)
    open_accounts = getattr(client, "open_accounts", None)
    if not callable(open_accounts):
        return searchers
    for name in dict.fromkeys(accounts):
        if name == PRIMARY_ACCOUNT:
            continue
        try:
            searchers.append(open_accounts([name])[name].client)
        except (AccountUnavailable, ImmichAPIError, httpx.HTTPError, OSError) as exc:
            logger.warning(
                "Could not open account %r for the personal-document search: %s", name, exc
            )
    return searchers


def _bulk_prefilter(client: object, accounts: Sequence[str]) -> frozenset[str] | None:
    """Every asset any configured account's keyword search turns up for a
    personal-document word, or None when no account here can search Immich's metadata."""
    searchers = _search_clients(client, accounts)
    if not searchers:
        return None
    found: set[str] = set()
    for searcher in searchers:
        reader = ImmichPrintedText(cast(Any, searcher))
        for word in _OCR_PREFILTER_WORDS:
            found.update(reader.pictures_reading(word))
    return frozenset(found)


class _MemoisedOcrReader:
    """The state one `document_ocr_port` closure used to hold: a read is tried once, a
    failure disables every read after it, and the bulk prefilter is computed once."""

    def __init__(
        self, get_text: Callable[[str], str | None], client: object, accounts: Sequence[str]
    ) -> None:
        self._get_text = get_text
        self._client = client
        self._accounts = accounts
        self._disabled = False
        self._cache: dict[str, str | None] = {}
        self._prefilter: frozenset[str] | None = None
        self._prefilter_read = False

    def _candidates(self) -> frozenset[str] | None:
        if self._prefilter_read:
            return self._prefilter
        self._prefilter_read = True
        try:
            self._prefilter = _bulk_prefilter(self._client, self._accounts)
        except (ImmichAPIError, httpx.HTTPError, OSError) as exc:
            logger.warning(
                "Immich keyword search failed (%s); personal-document OCR is off for the "
                "rest of this run",
                exc,
            )
            self._disabled = True
            self._prefilter = None
        return self._prefilter

    def _excluded_by_prefilter(self, asset_id: str, frame_is_document_like: bool) -> bool:
        # An MRZ line, a Luhn card number or an IBAN can never be found by a keyword
        # search, so a frame the head already calls document-like is read regardless.
        if frame_is_document_like:
            return False
        narrowed = self._candidates()
        return narrowed is not None and asset_id not in narrowed

    def text_of(self, asset_id: str, frame_is_document_like: bool = False) -> str | None:
        if asset_id in self._cache:
            return self._cache[asset_id]
        if self._disabled:
            return None
        if self._excluded_by_prefilter(asset_id, frame_is_document_like) or self._disabled:
            self._cache.setdefault(asset_id, None)
            return None
        try:
            text = self._get_text(asset_id)
        except (ImmichAPIError, httpx.HTTPError, OSError) as exc:
            logger.warning(
                "Immich OCR read failed (%s); personal-document OCR is off for the rest of this run",
                exc,
            )
            self._disabled = True
            return None
        self._cache[asset_id] = text
        return text


def document_ocr_port(
    client: object, *, accounts: Sequence[str] = ()
) -> Callable[[str, bool], str | None] | None:
    """This run's per-asset OCR text reader, or None when it has no OCR to offer (#2062).

    A read failure once the signal is live disables it for the rest of this run and logs
    once: a transient Immich error must not hold the whole library, and must not spam the
    log either. A failing bulk search does the same -- it is read inside the same guard a
    per-asset read failure is.

    Every read is memoised by asset id, shared across the material build, a candidate
    refresh and the audience gate -- the same picture is never read twice in one run. When
    an account can search Immich's metadata, a bulk keyword search (`_bulk_prefilter`)
    narrows the library once to the assets worth the expensive per-asset read at all; an
    asset the search never turns up reads as having no personal-record text, with no
    read -- unless the caller already knows the frame itself is document-like
    (`frame_is_document_like`), in which case the read happens anyway: an MRZ line, a Luhn
    card number or an IBAN can never be found by a keyword search.
    """
    get_text = _ocr_capable_reader(client)
    if get_text is None:
        return None
    return _MemoisedOcrReader(get_text, client, accounts).text_of
