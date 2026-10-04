"""Known screen and document sources remain evidence, never scene carriers."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Collection, Mapping

import httpx

from immich_memories.analysis.annotation_line_fields import content_of
from immich_memories.api.immich import ImmichAPIError

logger = logging.getLogger(__name__)

# The Immich server version that first answers GET /assets/{id}/ocr (#2062).
_OCR_MIN_VERSION = (2, 2)

# The kinds of frame that carry nothing a film can show, against the ones that do. This is
# the `frame_kind` head's label set, split the way the standing gate reads it.
NOTHING_KINDS = frozenset(
    {
        "empty_room_ceiling_or_floor",
        "accidental_or_blurred_frame",
        "lone_everyday_object",
        "body_part_closeup",
    }
)
CARRYING_KINDS = frozenset(
    {
        "people_moment",
        "place_or_scenery",
        "meaningful_record",
        "screen_or_document",
    }
)

SCREEN_DOCUMENT_LABELS = frozenset(
    {
        "screenshot_from_computer",
        "screenshot_from_manual",
        "geographical_map",
        "table",
        "line_chart",
        "bar_chart",
        "scatter_plot",
        "flow_chart",
        "qr_code",
        "bar_code",
        "calendar",
        "page_thumbnail",
        "full_page_image",
        "logo",
        "signature",
        "engineering_drawing",
    }
)
_DOCUMENT_FIELD = re.compile(r"(?:^|[|,])\s*document=([a-z_]+)(?=\s*(?:[,|]|$))")
SCREEN_HEAD_YES = "yes"
_SCREEN_HEAD_FIELD = re.compile(rf"(?:^|[|,])\s*screen={SCREEN_HEAD_YES}(?=\s*(?:[,|]|$))")


def screen_flagged(heads: Mapping[str, str]) -> bool:
    """The distilled screen head says this frame is one. It only adds to the document head.

    It ships at a band strict enough that over 3,564 photographs it answered yes on 37 and
    every one of them was a screen, so reading it beside `doc_docling` buys nine more
    screens for no extra false refusal. A bank with no `screen` row reads as it always did.
    """
    return heads.get("screen") == SCREEN_HEAD_YES


def screen_flagged_on_line(line: str) -> bool:
    """The same head, read off a rendered line instead of a head mapping."""
    return bool(_SCREEN_HEAD_FIELD.search(line))


_SCREEN_TEXT = re.compile(
    r"\b(screenshot|screen (displaying|showing)|phone screen|computer screen|"
    r"monitor displaying|app interface|tv screen|laptop screen|projector screen)\b",
    re.IGNORECASE,
)


# Phone screen pixel sizes (portrait). A photo never has exactly these dimensions; a screenshot always does.
PHONE_SCREEN_SIZES = frozenset(
    {
        (640, 1136),
        (750, 1334),
        (1080, 1920),
        (1125, 2436),
        (1170, 2532),
        (1179, 2556),
        (1206, 2622),
        (1242, 2208),
        (1242, 2688),
        (1284, 2778),
        (1290, 2796),
        (1320, 2868),
        (828, 1792),
        (1080, 2340),
        (1080, 2400),
        (1440, 3120),
        (1440, 3200),
        (1344, 2992),
    }
)
_RESOLUTION_FIELD = re.compile(r"resolution:(\d{3,4})x(\d{3,4})")


_FACE_CLOSE_UP = re.compile(
    r"(composition|subject_action):[^|]*?\bclose-?up\b[^|]*?\b(face|eye|eyes|nose|forehead|mouth|lips|teeth|skin|chin)\b",
    re.IGNORECASE,
)


_MEDICAL_CARE = re.compile(
    r"\b(eye mask|gel mask|ice pack|cold pack|cold compress|compress on|bandage|band-aid|plaster on|thermometer|"
    r"iv drip|iv line|swollen|rash|infection|nasal cannula|stitches)\b",
    re.IGNORECASE,
)
_IDENTICAL_GRID = re.compile(
    r"(identical|same) (images|photos|pictures|portraits)[^|]{0,60}\b(grid|panel|panels|sheet)\b|"
    r"\b(passport photos?|id photos?|photo booth strip|photo-booth)\b",
    re.IGNORECASE,
)


def medical_care(content: str) -> bool:
    """An ailment or a care item on a person: intimate care, never a carrier. Reads the
    picture's content (`content_of`), not the whole line."""
    return bool(_MEDICAL_CARE.search(content))


def identical_grid(content: str) -> bool:
    """A sheet of identical portraits is an identification document, whatever the detector called it."""
    return bool(_IDENTICAL_GRID.search(content))


def face_close_up(content: str) -> bool:
    """The detector's composition fact says close-up of a face part: a picture that needs an
    explanation, never a carrier (it stays evidence)."""
    return bool(_FACE_CLOSE_UP.search(content))


def screenshot_by_resolution(line: str) -> bool:
    """A STILL whose pixel size is a phone screen size. A phone records portrait video at exactly
    these sizes, and a Live Photo renders from its still, so neither is ever a screenshot."""
    if "VIDEO" in line or "LIVE PHOTO" in line:
        return False
    match = _RESOLUTION_FIELD.search(line)
    if not match:
        return False
    w, h = int(match.group(1)), int(match.group(2))
    return (min(w, h), max(w, h)) in PHONE_SCREEN_SIZES


_PERSONAL_DOCUMENT_TEXT = re.compile(
    r"\b(?:identity cards?|id cards?|passports?|driver'?s? licen[cs]es?|driving licen[cs]es?|"
    r"(?:bank|credit|debit) cards?|(?:bank|credit|debit) statements?|boarding passe?s?|"
    r"(?:a |an )?(?:letter|form) (?:addressed to|with|showing)[^|]*?"
    r"(?:name and address|date of birth|personal details|account number))\b",
    re.IGNORECASE,
)

# Only these frame kinds carry a personal document at all; an incidental document in a
# people_moment or place_or_scenery frame is not the frame's subject (#2062). A frame_kind
# that is missing (no head computed, or no heads at all on Basic) is not a disqualification:
# OCR is all Basic has, and it must be allowed to stand on its own.
_DOCUMENT_LIKE_FRAMES = frozenset({"screen_or_document", "meaningful_record"})

# The machine-readable zone on a passport or ID card pads every line to a fixed width with
# angle brackets; two or more such runs is not a sequence an ordinary caption, sign or menu
# ever produces.
_MRZ_LINE = re.compile(r"<{5,}")
# A 13-19 digit run (a card number) or an IBAN-shaped code.
_DIGIT_RUN = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")

# Personal-record field labels a passport, ID card, bank card, payslip or medical record
# prints, across the household's own languages and the field names the owner named directly
# (NISS/numéro national, the Belgian national number). Not exhaustive: a locale missing here
# still gets the caption, MRZ and card/IBAN-number signals.
_PERSONAL_RECORD_FIELD = re.compile(
    r"\b(?:"
    # English
    r"date of birth|place of birth|nationality|card ?holder|holder'?s? name|"
    r"social security(?: number)?|national (?:insurance|number)|passport no\.?|"
    # French / Belgian French
    r"date de naissance|n[ée]\(?e\)? le|lieu de naissance|num[ée]ro national|niss|"
    r"titulaire|nom et pr[ée]nom|nom de naissance|"
    # Dutch / Belgian Dutch
    r"geboortedatum|geboorteplaats|nationaliteit|identiteitskaart|rijksregisternummer|"
    # German
    r"geburtsdatum|geburtsort|staatsangeh[öo]rigkeit|ausweisnummer|"
    # Spanish
    r"fecha de nacimiento|lugar de nacimiento|nacionalidad|n[úu]mero de identificaci[óo]n|"
    # Italian
    r"data di nascita|luogo di nascita|nazionalit[àa]|codice fiscale|"
    # Portuguese
    r"data de nascimento|naturalidade|nacionalidade|"
    # Nordic / Finnish
    r"f[øö]dselsdato|f[øö]dselsnummer|personnummer|henkil[öo]tunnus|"
    # Polish / Romanian / Czech
    r"data urodzenia|numer pesel|data na[sş]terii|cod numeric personal|rodn[ée] [čc]íslo"
    r")\b",
    re.IGNORECASE,
)


def _luhn_valid(run: str) -> bool:
    """The check digit a card number (not an arbitrary long number) must satisfy."""
    digits = [int(ch) for ch in run if ch.isdigit()]
    if len(digits) < 13:
        return False
    total = 0
    for index, digit in enumerate(reversed(digits)):
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def ocr_reads_a_personal_record(ocr_text: str | None) -> bool:
    """Immich's own OCR text names a personal-record field, a passport's machine-readable
    zone, or a Luhn-valid card number / IBAN -- evidence no caption or head can give (#2062)."""
    if not ocr_text:
        return False
    return bool(
        _PERSONAL_RECORD_FIELD.search(ocr_text)
        or len(_MRZ_LINE.findall(ocr_text)) >= 2
        or _IBAN.search(ocr_text)
        or any(_luhn_valid(run) for run in _DIGIT_RUN.findall(ocr_text))
    )


def personal_document(content: str, heads: Mapping[str, str], ocr_text: str | None = None) -> bool:
    """A photographed ID card or personal document, caught where the detector heads cannot.

    `doc_docling` has no identity-document label: it names figure types (charts, tables,
    logos, a screenshot) and falls back to its catch-all `photograph` for anything else,
    the same label an ordinary photo gets, and `frame_kind`'s `screen_or_document` is one
    label for every screen and document, legitimate records included -- on the public
    held-out set 42 of 51 such frames were worth keeping (#1539's own measurement). Neither
    head tells a photographed passport apart from a race certificate on its own, so this
    reads the content instead: a caption naming the document, or Immich's OCR reading an
    actual personal-record field, an MRZ line or a card number. The frame head only narrows
    which pictures that evidence counts for, to an explicit non-document frame kind (#2062).
    """
    if _PERSONAL_DOCUMENT_TEXT.search(content):
        return True
    frame = heads.get("frame_kind")
    if frame is not None and frame not in _DOCUMENT_LIKE_FRAMES:
        return False
    return ocr_reads_a_personal_record(ocr_text)


def excluded_carrier_sources(
    annotations: Mapping[str, str],
    *,
    heads_of: Mapping[str, Mapping[str, str]] | None = None,
    ocr_text_of: Callable[[str], str | None] | None = None,
    protected: Collection[str] = (),
) -> dict[str, str]:
    """Use grounded annotation fields, without reclassifying the event's importance.

    A map mentioned in a real scene is not the same as a geographical-map document
    label. No date, filename, person or sporting-event name is part of this rule.
    `protected` pictures (only an explicit owner pin, `owner_required_asset_ids`) skip the
    personal-document check only: the owner's own choice stands.
    """
    excluded = {}
    heads_of = heads_of or {}
    for asset_id, line in annotations.items():
        # The heads and the pixel size are our own fields and are read as such; the words a
        # rule looks for are read only where the picture's content is, so a burst that
        # "stitches to a clip", a place or a person's name never matches them (#1256).
        content = content_of(line)
        document = _DOCUMENT_FIELD.search(line)
        if document and document.group(1) in SCREEN_DOCUMENT_LABELS:
            excluded[asset_id] = f"document-head:{document.group(1)}"
        elif screen_flagged_on_line(line):
            excluded[asset_id] = "screen-head"
        elif _SCREEN_TEXT.search(content):
            excluded[asset_id] = "screen-description"
        elif screenshot_by_resolution(line):
            excluded[asset_id] = "screenshot-resolution"
        elif face_close_up(content):
            excluded[asset_id] = "face-close-up"
        elif medical_care(content):
            excluded[asset_id] = "medical-care"
        elif identical_grid(content):
            excluded[asset_id] = "identical-grid"
        elif asset_id not in protected and personal_document(
            content,
            heads_of.get(asset_id, {}),
            ocr_text_of(asset_id) if ocr_text_of else None,
        ):
            excluded[asset_id] = "personal-document"
    return excluded


def document_ocr_port(client: object) -> Callable[[str], str | None] | None:
    """This run's per-asset OCR text reader, or None when it has no OCR to offer (#2062).

    A server below 2.2, or a client with no asset-OCR or version read at all, skips the
    signal rather than ask every candidate and fail the same way each time. A read failure
    once the signal is live disables it for the rest of this run and logs once: a transient
    Immich error must not hold the whole library, and must not spam the log either. The
    caption and head signals this read corroborates still apply on their own.
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
    disabled = False

    def ocr_text_of(asset_id: str) -> str | None:
        nonlocal disabled
        if disabled:
            return None
        try:
            return get_text(asset_id)
        except (ImmichAPIError, httpx.HTTPError, OSError) as exc:
            logger.warning(
                "Immich OCR read failed (%s); personal-document OCR is off for the rest of this run",
                exc,
            )
            disabled = True
            return None

    return ocr_text_of
