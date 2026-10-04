"""A photographed ID card, passport or personal document never carries a scene (#2062).

`doc_docling` has no identity-document label: it names figure types (charts, tables, logos)
and falls back to `photograph` for anything else, the same label an ordinary photo gets, and
`frame_kind`'s `screen_or_document` also catches legitimate records. A caption that names the
document, or Immich's own OCR reading an actual personal-record field, an MRZ line or a card
number, is the evidence that tells the two apart; the frame head only narrows which frames
that evidence counts for.
"""

import pytest

from immich_memories.analysis.editorial_carrier_eligibility import excluded_carrier_sources


def test_a_caption_naming_a_passport_is_refused_on_every_tier():
    lines = {"card": "2024-02-04 09:00+00:00 | A photo of a passport on the table"}
    assert excluded_carrier_sources(lines) == {"card": "personal-document"}


def test_a_caption_naming_an_id_card_is_refused():
    lines = {"card": "2024-02-04 09:00+00:00 | Someone holds up an id card to the camera"}
    assert excluded_carrier_sources(lines) == {"card": "personal-document"}


def test_a_french_medical_receipt_with_a_national_number_is_refused():
    # A meaningful_record frame: the 42-of-51 gap #1539 found means the head alone must
    # never fire, but real OCR text naming a national-number field does.
    lines = {"receipt": "2024-02-04 09:00+00:00"}
    excluded = excluded_carrier_sources(
        lines,
        heads_of={"receipt": {"frame_kind": "meaningful_record"}},
        ocr_text_of={
            "receipt": "MUTUALITE CHRETIENNE\nNuméro national: 85.04.12-345-67\nMontant: 42,50 EUR"
        }.get,
    )
    assert excluded == {"receipt": "personal-document"}


def test_an_event_voucher_with_a_name_in_french_ocr_is_refused():
    lines = {"voucher": "2024-02-04 09:00+00:00"}
    excluded = excluded_carrier_sources(
        lines,
        heads_of={"voucher": {"frame_kind": "meaningful_record"}},
        ocr_text_of={"voucher": "BILLET D'ENTREE\nNom et prénom: Durand Marie\nValable 1 jour"}.get,
    )
    assert excluded == {"voucher": "personal-document"}


def test_the_document_head_plus_ocr_corroborate_a_photographed_card_with_no_caption():
    # no_captions / GPU tier: heads are read, but there is no caption text to match.
    lines = {"card": "2024-02-04 09:00+00:00"}
    excluded = excluded_carrier_sources(
        lines,
        heads_of={"card": {"frame_kind": "screen_or_document", "doc_docling": "photograph"}},
        ocr_text_of={"card": "PASSPORT\nDate of birth: 02 JAN 1990"}.get,
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
    excluded = excluded_carrier_sources(
        lines, ocr_text_of={"card": "PASSPORT\nDate of birth: 02 JAN 1990"}.get
    )
    assert excluded == {"card": "personal-document"}


def test_an_mrz_line_refuses_even_with_no_field_label_matched():
    lines = {"passport": "2024-02-04 09:00+00:00"}
    mrz = (
        "P<BELDURAND<<MARIE<<<<<<<<<<<<<<<<<<<<<<<<<\n1234567890BEL9001029F3001011<<<<<<<<<<<<<<04"
    )
    excluded = excluded_carrier_sources(
        lines,
        heads_of={"passport": {"frame_kind": "meaningful_record"}},
        ocr_text_of={"passport": mrz}.get,
    )
    assert excluded == {"passport": "personal-document"}


def test_a_luhn_valid_card_number_refuses():
    lines = {"card": "2024-02-04 09:00+00:00"}
    excluded = excluded_carrier_sources(
        lines,
        heads_of={"card": {"frame_kind": "meaningful_record"}},
        ocr_text_of={"card": "VALID THRU 12/29\n4539 1488 0343 6467"}.get,
    )
    assert excluded == {"card": "personal-document"}


def test_a_people_moment_frame_is_never_refused_on_ocr_alone():
    # A document incidentally visible in someone's hand is not the frame's own subject.
    lines = {"photo": "2024-02-04 09:00+00:00"}
    excluded = excluded_carrier_sources(
        lines,
        heads_of={"photo": {"frame_kind": "people_moment"}},
        ocr_text_of={"photo": "PASSPORT\nDate of birth: 02 JAN 1990"}.get,
    )
    assert excluded == {}


def test_a_street_sign_is_not_a_personal_document():
    lines = {"sign": "2024-02-04 09:00+00:00 | A street sign points towards the old town"}
    assert excluded_carrier_sources(lines) == {}


def test_an_event_programme_is_not_a_personal_document():
    lines = {"programme": "2024-02-04 09:00+00:00 | A concert programme lies on the seat"}
    assert excluded_carrier_sources(lines) == {}


def test_a_menu_is_not_a_personal_document():
    lines = {"menu": "2024-02-04 09:00+00:00"}
    excluded = excluded_carrier_sources(
        lines,
        heads_of={"menu": {"frame_kind": "meaningful_record"}},
        ocr_text_of={
            "menu": "MENU DU JOUR\nEntree 8 EUR\nPlat principal 16 EUR\nDessert 6 EUR"
        }.get,
    )
    assert excluded == {}


def test_a_museum_label_is_not_a_personal_document():
    lines = {"label": "2024-02-04 09:00+00:00"}
    excluded = excluded_carrier_sources(
        lines,
        heads_of={"label": {"frame_kind": "meaningful_record"}},
        ocr_text_of={"label": "Still Life with Flowers, 1874\nOil on canvas\nDonated 1921"}.get,
    )
    assert excluded == {}


def test_a_pinned_personal_document_is_kept():
    lines = {"card": "2024-02-04 09:00+00:00 | A photo of a passport on the table"}
    excluded = excluded_carrier_sources(lines, protected={"card"})
    assert excluded == {}


def test_a_favourite_personal_document_is_not_protected():
    # Only an explicit owner pin (owner_required_asset_ids) is exempt; a favourite star is
    # not the owner choosing to ship a readable document.
    lines = {"card": "2024-02-04 09:00+00:00 | A photo of a passport on the table"}
    assert excluded_carrier_sources(lines) == {"card": "personal-document"}


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

    # A favourite star is not an owner pin: it never exempts a personal document.
    expected = {} if protection == "required" else {asset_id: "personal-document"}
    assert material.document_sources == expected
    selectable = {unit["asset_id"] for units in material.units.values() for unit in units}
    assert (asset_id in selectable) == (protection == "required")
