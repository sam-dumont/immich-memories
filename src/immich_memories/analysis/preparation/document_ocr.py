"""The run's per-asset OCR text reader, bounded to a cold year under an hour (#2062).

Split out of `runtime/composition.py` (round 3): reading a personal document's OCR text is one
cohesive unit (version gate, memoisation), separate from the rest of that module's production
wiring.
"""

from __future__ import annotations

import logging
import weakref
from collections.abc import Callable
from typing import Any

import httpx

from immich_memories.api.immich import ImmichAPIError

logger = logging.getLogger(__name__)

_OCR_MIN_VERSION = (2, 2)

OcrTextOf = Callable[[str, bool], "str | None"]

# One reader per live client, so every caller in a run (the material build, a candidate
# refresh, the audience gate, the period account's own screen) shares one memo and one
# version read. The reader holds its client weakly, so the entry goes when the client does.
_READERS: weakref.WeakKeyDictionary[Any, _MemoisedOcrReader] = weakref.WeakKeyDictionary()


def _ocr_capable(client: object) -> bool:
    """Whether `client`'s server proves it's 2.2+ and it can read an asset's OCR text.

    Anything that keeps this from being certain -- no method, no version, too old a server
    -- skips the signal outright rather than ask every candidate and fail the same way
    every time.
    """
    get_server_info = getattr(client, "get_server_info", None)
    if not callable(get_server_info) or not callable(getattr(client, "get_asset_ocr_text", None)):
        return False
    try:
        info = get_server_info()
    except (ImmichAPIError, httpx.HTTPError, OSError) as exc:
        logger.warning(
            "Could not read Immich's server version; personal-document OCR is off: %s", exc
        )
        return False
    if (info.major, info.minor) < _OCR_MIN_VERSION:
        logger.info(
            "Immich %s predates per-asset OCR reads; personal-document OCR is off",
            info.version_string,
        )
        return False
    return True


class _MemoisedOcrReader:
    """A read is tried once per asset, and a failure disables every read after it."""

    def __init__(self, client: Any) -> None:
        self._client = weakref.ref(client)
        self._disabled = False
        self._cache: dict[str, str | None] = {}

    def text_of(self, asset_id: str, frame_is_document_like: bool) -> str | None:
        # `personal_document` reads OCR text only for a frame its head leaves document-like;
        # for any other frame the answer cannot change the verdict, so Immich is not asked.
        if not frame_is_document_like:
            return None
        if asset_id in self._cache:
            return self._cache[asset_id]
        client = self._client()
        if self._disabled or client is None:
            return None
        try:
            text = client.get_asset_ocr_text(asset_id)
        except (ImmichAPIError, httpx.HTTPError, OSError) as exc:
            logger.warning(
                "Immich OCR read failed (%s); personal-document OCR is off for the rest of this run",
                exc,
            )
            self._disabled = True
            return None
        self._cache[asset_id] = text
        return text


def document_ocr_port(client: object) -> OcrTextOf | None:
    """This run's per-asset OCR text reader, or None when it has no OCR to offer (#2062).

    The reader answers None without a request for a frame its head calls non-document
    (`frame_is_document_like` False): `personal_document` never reads OCR text for such a
    frame, so asking Immich could not change the verdict. A document-like frame is read
    once per asset: an MRZ line, a Luhn card number or an IBAN is only found this way.

    A read failure once the signal is live disables it for the rest of this run and logs
    once: a transient Immich error must not hold the whole library, and must not spam the
    log either. The reader is shared per client, so the same picture is never read twice
    while that client lives -- across the material build, a candidate refresh, the audience
    gate and the period account alike. Reads go through `client`, which routes each asset
    to the account that owns it (`AccessBoundClient`).
    """
    try:
        shared = _READERS.get(client)
    except TypeError:  # WHY: a client that cannot be weakly referenced has no OCR reader
        return None
    if shared is not None:
        return shared.text_of
    if not _ocr_capable(client):
        return None
    reader = _MemoisedOcrReader(client)
    _READERS[client] = reader
    return reader.text_of
