"""The matrix's factual screen/document gate, shared with production acquisition."""

from __future__ import annotations

import re
from collections.abc import Callable, Collection

from immich_memories.analysis.annotation_lines import AnnotationLineBatch
from immich_memories.analysis.editorial_carrier_eligibility import (
    personal_document,
    screen_flagged,
    screenshot_by_resolution,
)

SCREEN_DOCUMENT_GATE_VERSION = "screen-document-source-gate-v1"

SCREEN_DOCUMENT_HEAD_LABELS = frozenset(
    {
        "screenshot_from_computer",
        "screenshot_from_manual",
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

SCREEN_DOCUMENT_TEXT = re.compile(
    r"\b(smart ?watch|screenshot|screen (displaying|showing)|phone screen|computer screen|"
    r"monitor displaying|app interface|dashboard|television|tv screen|tv show|laptop screen|"
    r"watching (a|the) (tv|screen|television)|projector screen)\b",
    re.IGNORECASE,
)


def screen_document_rejections(
    batch: AnnotationLineBatch,
    *,
    ocr_text_of: Callable[[str], str | None] | None = None,
    protected: Collection[str] = (),
) -> dict[str, str]:
    """Return the established hard source exclusions in stable input order.

    Only an explicit owner pin (`protected`) is exempt from the personal-document check: a
    favourite star is not the owner choosing to ship a readable document (#2062).
    """
    rejected: dict[str, str] = {}
    for line in batch.lines:
        heads = dict(line.heads)
        label = heads.get("doc_docling")
        if label in SCREEN_DOCUMENT_HEAD_LABELS:
            rejected[line.asset_id] = f"screen-docling:{label}"
        elif screen_flagged(heads):
            rejected[line.asset_id] = "screen-head"
        elif line.description and SCREEN_DOCUMENT_TEXT.search(line.description):
            rejected[line.asset_id] = "screen-text"
        elif screenshot_by_resolution(line.text):
            # A pixel size is metadata, so this arm answers with or without a caption
            # seat. It is already the carrier rule; a screenshot was never a source.
            rejected[line.asset_id] = "screenshot-resolution"
        elif line.asset_id not in protected and personal_document(
            line.description or "",
            heads,
            ocr_text_of(line.asset_id) if ocr_text_of else None,
        ):
            rejected[line.asset_id] = "personal-document"
    return rejected
