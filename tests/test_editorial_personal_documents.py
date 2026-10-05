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


def test_a_caption_naming_a_document_excludes_it_even_in_an_ordinary_scene():
    # The owner's stance: a caption naming the document excludes outright, with no
    # frame-head narrowing. Only the OCR/field-evidence path respects the frame head.
    lines = {
        "family": "2024-02-04 09:00+00:00 | A family holds up their boarding passes at the gate"
    }
    excluded = excluded_carrier_sources(lines, heads_of={"family": {"frame_kind": "people_moment"}})
    assert excluded == {"family": "personal-document"}


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


# -- Round 3: the owner replayed this against a real Immich 3.2.4 and 0 of 5 campaign
# outcomes were excluded (false positives stayed at 0 of 200). The word-list OCR signal
# never fired; these fixtures exercise the actual-text analysis that replaced it (#2062).


def test_a_document_title_word_alone_is_enough_in_any_of_the_covered_languages():
    lines = {"card": "2024-02-04 09:00+00:00"}
    for title in ("PASSEPORT", "rijbewijs", "Personalausweis", "身份证", "паспорт", "DNI"):
        excluded = excluded_carrier_sources(
            lines,
            heads_of={"card": {"frame_kind": "meaningful_record"}},
            ocr_text_of={"card": title}.get,
        )
        assert excluded == {"card": "personal-document"}, title


def test_ne_le_matches_with_or_without_the_feminine_suffix():
    lines = {"a": "2024-02-04", "b": "2024-02-04", "c": "2024-02-04"}
    for asset_id, text in (
        ("a", "né le 4 janvier"),
        ("b", "née le 4 janvier"),
        ("c", "né(e) le 4 janvier"),
    ):
        excluded = excluded_carrier_sources(
            {asset_id: lines[asset_id]},
            heads_of={asset_id: {"frame_kind": "meaningful_record"}},
            ocr_text_of={asset_id: text}.get,
        )
        assert excluded == {asset_id: "personal-document"}, text


def test_an_eu_licence_needs_both_its_title_and_a_numbered_field():
    lines = {"licence": "2024-02-04", "partial": "2024-02-04"}
    full = excluded_carrier_sources(
        {"licence": lines["licence"]},
        heads_of={"licence": {"frame_kind": "meaningful_record"}},
        ocr_text_of={"licence": "DRIVING LICENCE\n4a. 01.01.2020\n4b. 01.01.2030"}.get,
    )
    assert full == {"licence": "personal-document"}
    # The title word alone is already enough (it's in the document-title list), so this
    # checks the numbered field doesn't fire without ANY document evidence around it.
    numbered_only = excluded_carrier_sources(
        {"partial": lines["partial"]},
        heads_of={"partial": {"frame_kind": "meaningful_record"}},
        ocr_text_of={"partial": "ORDER FORM\n4a. widgets\n4b. gadgets"}.get,
    )
    assert numbered_only == {}


def test_a_gift_voucher_naming_who_it_is_for_is_refused():
    lines = {"voucher": "2024-02-04"}
    excluded = excluded_carrier_sources(
        {"voucher": lines["voucher"]},
        heads_of={"voucher": {"frame_kind": "meaningful_record"}},
        ocr_text_of={"voucher": "GUTSCHEIN\nFür: Anna"}.get,
    )
    assert excluded == {"voucher": "personal-document"}


def test_a_voucher_with_no_name_field_is_kept():
    lines = {"voucher": "2024-02-04"}
    excluded = excluded_carrier_sources(
        {"voucher": lines["voucher"]},
        heads_of={"voucher": {"frame_kind": "meaningful_record"}},
        ocr_text_of={"voucher": "VOUCHER\n10% off your next visit"}.get,
    )
    assert excluded == {}


def test_an_order_number_is_not_read_as_a_card_number():
    lines = {"receipt": "2024-02-04"}
    excluded = excluded_carrier_sources(
        {"receipt": lines["receipt"]},
        heads_of={"receipt": {"frame_kind": "meaningful_record"}},
        ocr_text_of={"receipt": "Order number: 4539148803436467\nThank you"}.get,
    )
    assert excluded == {}


def test_a_mod_97_valid_iban_is_refused_an_invalid_one_is_kept():
    lines = {"valid": "2024-02-04", "invalid": "2024-02-04"}
    valid = excluded_carrier_sources(
        {"valid": lines["valid"]},
        heads_of={"valid": {"frame_kind": "meaningful_record"}},
        ocr_text_of={"valid": "IBAN: BE68539007547034"}.get,
    )
    assert valid == {"valid": "personal-document"}
    invalid = excluded_carrier_sources(
        {"invalid": lines["invalid"]},
        heads_of={"invalid": {"frame_kind": "meaningful_record"}},
        ocr_text_of={"invalid": "REF: XX00ABCDEFGH1234567"}.get,
    )
    assert invalid == {}


def test_a_grouped_iban_is_also_checked_against_mod_97():
    lines = {"grouped": "2024-02-04"}
    excluded = excluded_carrier_sources(
        {"grouped": lines["grouped"]},
        heads_of={"grouped": {"frame_kind": "meaningful_record"}},
        ocr_text_of={"grouped": "IBAN: BE68 5390 0754 7034"}.get,
    )
    assert excluded == {"grouped": "personal-document"}


# -- Round 4: the owner's real replay turned up new false positives to fix without
# losing the recall round 3 won (#2062).


def test_ne_le_jetez_pas_does_not_match_the_birth_date_field():
    lines = {"bin": "2024-02-04"}
    excluded = excluded_carrier_sources(
        {"bin": lines["bin"]},
        heads_of={"bin": {"frame_kind": "meaningful_record"}},
        ocr_text_of={"bin": "Ne le jetez pas dans la nature"}.get,
    )
    assert excluded == {}


def test_patented_does_not_match_the_italian_licence_title_word():
    lines = {"product": "2024-02-04"}
    excluded = excluded_carrier_sources(
        {"product": lines["product"]},
        heads_of={"product": {"frame_kind": "meaningful_record"}},
        ocr_text_of={"product": "THIS DESIGN IS PATENTED"}.get,
    )
    assert excluded == {}


@pytest.mark.parametrize("pass_kind", ["ski pass", "bus pass", "day pass"])
def test_a_generic_pass_is_not_a_personal_document(pass_kind):
    lines = {"pass": "2024-02-04"}
    excluded = excluded_carrier_sources(
        {"pass": lines["pass"]},
        heads_of={"pass": {"frame_kind": "meaningful_record"}},
        ocr_text_of={"pass": f"{pass_kind.upper()}\nvalid today"}.get,
    )
    assert excluded == {}


def test_a_boarding_pass_is_still_a_personal_document():
    # Unlike a ski/bus/day pass, a real boarding pass carries the traveller's name.
    lines = {"pass": "2024-02-04"}
    excluded = excluded_carrier_sources(
        {"pass": lines["pass"]},
        heads_of={"pass": {"frame_kind": "meaningful_record"}},
        ocr_text_of={"pass": "BOARDING PASS\nPassenger: John Smith"}.get,
    )
    assert excluded == {"pass": "personal-document"}


def test_bon_pour_un_cafe_is_not_a_voucher_with_a_name():
    lines = {"menu": "2024-02-04"}
    excluded = excluded_carrier_sources(
        {"menu": lines["menu"]},
        heads_of={"menu": {"frame_kind": "meaningful_record"}},
        ocr_text_of={"menu": "Bon pour un café offert"}.get,
    )
    assert excluded == {}


def test_a_two_line_machine_readable_zone_is_required():
    lines = {"a": "2024-02-04", "b": "2024-02-04"}
    one_line = excluded_carrier_sources(
        {"a": lines["a"]},
        heads_of={"a": {"frame_kind": "meaningful_record"}},
        ocr_text_of={"a": "<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<"}.get,
    )
    assert one_line == {}
    two_lines = excluded_carrier_sources(
        {"b": lines["b"]},
        heads_of={"b": {"frame_kind": "meaningful_record"}},
        ocr_text_of={
            "b": "P<BELDURAND<<MARIE<<<<<<<<<<<<<<<<<<<<<<<<<\n"
            "1234567890BEL9001029F3001011<<<<<<<<<<<<<<04"
        }.get,
    )
    assert two_lines == {"b": "personal-document"}
