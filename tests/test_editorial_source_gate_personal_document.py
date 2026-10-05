"""`screen_document_rejections` is the one gate every route reads for a personal document (#2062).

The audience gate, the --ask preview and the --ask period accounts all call it (or its shared
`personal_document` predicate) with the same heads, caption and OCR facts, so a photographed
ID card is held consistently wherever a route checks for a screen or document source.
"""

from immich_memories.analysis.annotation_lines import AnnotationLineBatch, AssetAnnotationLine
from immich_memories.analysis.editorial_source_gate import screen_document_rejections


def _batch(*lines: AssetAnnotationLine) -> AnnotationLineBatch:
    from immich_memories.analysis.annotation_lines import AnnotationContract

    return AnnotationLineBatch(
        requested_asset_ids=tuple(line.asset_id for line in lines),
        lines=lines,
        missing_asset_ids=(),
        contract=AnnotationContract(renderer_version="v1", producer_versions=("v1",)),
    )


def test_a_meaningful_record_corroborated_by_ocr_is_refused():
    batch = _batch(
        AssetAnnotationLine("receipt", "2024-02-04", heads=(("frame_kind", "meaningful_record"),))
    )
    rejected = screen_document_rejections(
        batch, ocr_text_of={"receipt": "Numéro national: 85.04.12-345-67"}.get
    )
    assert rejected == {"receipt": "personal-document"}


def test_a_people_moment_is_never_refused_on_ocr_alone():
    batch = _batch(
        AssetAnnotationLine("photo", "2024-02-04", heads=(("frame_kind", "people_moment"),))
    )
    rejected = screen_document_rejections(
        batch, ocr_text_of={"photo": "PASSPORT\nDate of birth: 02 JAN 1990"}.get
    )
    assert rejected == {}


def test_an_owner_pin_is_exempt_but_a_favourite_star_is_not_tracked_here():
    # screen_document_rejections reads only annotation facts; favourite/pin status is the
    # caller's to withhold via `protected`, as every route here does uniformly.
    batch = _batch(
        AssetAnnotationLine(
            "card",
            "2024-02-04 | A photo of a passport on the table",
            description="A photo of a passport on the table",
        )
    )
    assert screen_document_rejections(batch, protected={"card"}) == {}
    assert screen_document_rejections(batch) == {"card": "personal-document"}
