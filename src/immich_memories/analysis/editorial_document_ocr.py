"""The run's per-asset OCR text reader, bounded to a cold year under an hour (#2062).

Split out of `editorial_runtime.py` (round 3): reading a personal document's OCR text is one
cohesive unit (version gate, bulk prefilter, memoisation), separate from the rest of that
module's production wiring.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, cast

import httpx

from immich_memories.api.immich import ImmichAPIError
from immich_memories.free_text.printed import ImmichPrintedText

logger = logging.getLogger(__name__)

# Immich's cheap, library-wide keyword search as a first pass: a personal document's own
# title or a field it prints, in the household's languages and scripts. Only assets one of
# these words turns up ever pay for the expensive per-asset OCR read below -- "a cold year
# under an hour" means never reading every asset's OCR text to find the few.
_OCR_PREFILTER_WORDS = (
    "passport",
    "passeport",
    "paspoort",
    "reisepass",
    "pasaporte",
    "passaporto",
    "passaporte",
    "paszport",
    "паспорт",
    "身份证",
    "驾驶证",
    "护照",
    "旅券",
    "주민등록증",
    "identity card",
    "carte d'identite",
    "identiteitskaart",
    "personalausweis",
    "carta d'identita",
    "dowod osobisty",
    "driving licence",
    "driving license",
    "permis de conduire",
    "rijbewijs",
    "fuhrerschein",
    "permiso de conducir",
    "patente",
    "carteira de identidade",
    "prawo jazdy",
    "korkort",
    "date of birth",
    "date de naissance",
    "geboortedatum",
    "geburtsdatum",
    "fecha de nacimiento",
    "data di nascita",
    "national insurance",
    "iban",
    "gutschein",
    "voucher",
    "bon",
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


def _bulk_prefilter(client: object) -> frozenset[str] | None:
    """Every asset Immich's own keyword search turns up for a personal-document word, or
    None when this client cannot search Immich's metadata at all."""
    if not callable(getattr(client, "search_metadata", None)):
        return None
    reader = ImmichPrintedText(cast(Any, client))
    found: set[str] = set()
    for word in _OCR_PREFILTER_WORDS:
        found.update(reader.pictures_reading(word))
    return frozenset(found)


def document_ocr_port(client: object) -> Callable[[str], str | None] | None:
    """This run's per-asset OCR text reader, or None when it has no OCR to offer (#2062).

    A read failure once the signal is live disables it for the rest of this run and logs
    once: a transient Immich error must not hold the whole library, and must not spam the
    log either.

    Every read is memoised by asset id, shared across the material build, a candidate
    refresh and the audience gate -- the same picture is never read twice in one run. When
    the client can search Immich's metadata, a bulk keyword search (`_bulk_prefilter`)
    narrows the library once to the assets worth the expensive per-asset read at all; an
    asset the search never turns up reads as having no personal-record text, with no read.
    """
    get_text = _ocr_capable_reader(client)
    if get_text is None:
        return None
    disabled = False
    cache: dict[str, str | None] = {}
    prefilter: frozenset[str] | None = None
    prefilter_read = False

    def candidates() -> frozenset[str] | None:
        nonlocal prefilter, prefilter_read
        if not prefilter_read:
            prefilter = _bulk_prefilter(client)
            prefilter_read = True
        return prefilter

    def ocr_text_of(asset_id: str) -> str | None:
        nonlocal disabled
        if asset_id in cache:
            return cache[asset_id]
        if disabled:
            return None
        narrowed = candidates()
        if narrowed is not None and asset_id not in narrowed:
            cache[asset_id] = None
            return None
        try:
            text = get_text(asset_id)
        except (ImmichAPIError, httpx.HTTPError, OSError) as exc:
            logger.warning(
                "Immich OCR read failed (%s); personal-document OCR is off for the rest of this run",
                exc,
            )
            disabled = True
            return None
        cache[asset_id] = text
        return text

    return ocr_text_of
