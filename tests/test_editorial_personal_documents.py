"""A photographed ID card, passport or personal document never carries a scene (#2062).

`doc_docling` has no identity-document label: it names figure types (charts, tables, logos)
and falls back to `photograph` for anything else, the same label an ordinary photo gets. A
caption that names the document, or Immich's OCR reading a personal-record field, is the
only evidence that tells the two apart.
"""

import pytest

from immich_memories.analysis.editorial_carrier_eligibility import excluded_carrier_sources


def test_a_caption_naming_a_passport_is_refused_on_every_tier():
    lines = {"card": "2024-02-04 09:00+00:00 | A photo of a passport on the table"}
    assert excluded_carrier_sources(lines) == {"card": "personal-document"}


def test_a_caption_naming_an_id_card_is_refused():
    lines = {"card": "2024-02-04 09:00+00:00 | Someone holds up an id card to the camera"}
    assert excluded_carrier_sources(lines) == {"card": "personal-document"}


def test_the_document_head_plus_ocr_corroborate_a_photographed_card_with_no_caption():
    # no_captions / GPU tier: heads are read, but there is no caption text to match.
    lines = {"card": "2024-02-04 09:00+00:00"}
    excluded = excluded_carrier_sources(
        lines,
        heads_of={"card": {"frame_kind": "screen_or_document", "doc_docling": "photograph"}},
        ocr_document_hits={"card"},
    )
    assert excluded == {"card": "personal-document"}


def test_the_document_head_alone_never_refuses_without_ocr_or_caption_corroboration():
    # The gap #1539 found: frame_kind=screen_or_document also catches legitimate records
    # (42 of 51 held-out frames were worth keeping), so the head alone must never fire.
    lines = {"record": "2024-02-04 09:00+00:00"}
    excluded = excluded_carrier_sources(
        lines,
        heads_of={"record": {"frame_kind": "screen_or_document", "doc_docling": "photograph"}},
    )
    assert excluded == {}


def test_basic_tier_with_no_heads_at_all_refuses_on_ocr_alone():
    # BASIC: no model heads are read; OCR reading a personal-record field is the only
    # evidence it has, and the owner's safety stance prefers a false positive here.
    lines = {"card": "2024-02-04 09:00+00:00"}
    excluded = excluded_carrier_sources(lines, ocr_document_hits={"card"})
    assert excluded == {"card": "personal-document"}


def test_a_street_sign_is_not_a_personal_document():
    lines = {"sign": "2024-02-04 09:00+00:00 | A street sign points towards the old town"}
    assert excluded_carrier_sources(lines) == {}


def test_an_event_programme_is_not_a_personal_document():
    lines = {"programme": "2024-02-04 09:00+00:00 | A concert programme lies on the seat"}
    assert excluded_carrier_sources(lines) == {}


def test_a_pinned_personal_document_is_kept():
    lines = {"card": "2024-02-04 09:00+00:00 | A photo of a passport on the table"}
    excluded = excluded_carrier_sources(lines, protected={"card"})
    assert excluded == {}


@pytest.mark.parametrize("protection", ["none", "favourite", "required"])
def test_planner_material_keeps_a_personal_document_only_when_the_owner_pinned_it(
    tmp_path, protection
):
    from dataclasses import replace

    from immich_memories.analysis.editorial_rule_reader import NoModelJudge
    from immich_memories.analysis.editorial_structure_contract import StructurePlannerPorts
    from immich_memories.analysis.editorial_structure_material import build_material, read_wall
    from tests.test_editorial_duration_planner_integration import source

    prepared = source(tmp_path, seconds=24, pictures=5)
    asset_id = "picture-000"
    records = dict(prepared.audience_annotations)
    records[asset_id] = replace(
        records[asset_id],
        text="2020-05-02T08:00:00+00:00 | A photo of a passport on the table",
    )
    prepared = replace(prepared, audience_annotations=records)
    annotations = dict(prepared.annotations)
    annotations[asset_id] = records[asset_id].text
    prepared = replace(prepared, annotations=annotations)
    if protection == "favourite":
        prepared.assets[asset_id].is_favorite = True
    elif protection == "required":
        prepared = replace(prepared, owner_required_asset_ids=(asset_id,))
    material = build_material(
        prepared,
        StructurePlannerPorts(judge=NoModelJudge(), thumbnail_hash=lambda _asset: None),
        read_wall(prepared),
    )

    expected = {asset_id: "personal-document"} if protection == "none" else {}
    assert material.document_sources == expected
    selectable = {unit["asset_id"] for units in material.units.values() for unit in units}
    assert (asset_id in selectable) == (protection != "none")
