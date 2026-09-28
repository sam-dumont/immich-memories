"""A picture's review explains proposals without confusing them with the final cut."""

import json

import pytest

from immich_memories.operations.cut_review import read_cut_decisions


def test_protected_picture_keeps_the_model_objection_and_the_rule_that_overruled_it(tmp_path):
    decisions = tmp_path / "derived-decisions"
    decisions.mkdir()
    (decisions / "thin-polish.private.json").write_text(
        json.dumps(
            {
                "ran": True,
                "verdicts": {
                    "original": {
                        "state": "kept",
                        "named_by": 2,
                        "why": "Another portrait from the same moment",
                        "protected": True,
                        "held_by": "the owner starred it or the catalogue records it",
                        "rule": "thesis-fit vote",
                    }
                },
                "slots": [],
            }
        )
    )

    review = read_cut_decisions(tmp_path)

    assert review["original"]["model_reason"] == "Another portrait from the same moment"
    assert review["original"]["kept_reason"] == "the owner starred it or the catalogue records it"
    assert review["original"]["proposed_asset_id"] == ""


def test_offered_alternatives_keep_the_actual_outcome_instead_of_claiming_a_swap(tmp_path):
    decisions = tmp_path / "derived-decisions"
    decisions.mkdir()
    (decisions / "thin-polish.private.json").write_text(
        json.dumps(
            {
                "ran": True,
                "verdicts": {"original": {"why": "Repeated view"}},
                "slots": [
                    {
                        "replacing": "original",
                        "chosen": "candidate",
                        "offered": "2",
                        "outcome": "refused by look-alike",
                    }
                ],
            }
        )
    )

    decision = read_cut_decisions(tmp_path)["original"]

    assert decision["offered_count"] == 2
    assert decision["replacement_outcome"] == "refused by look-alike"
    assert decision["proposed_asset_id"] == "candidate"


@pytest.mark.parametrize("payload", [None, "{unfinished", "[]"])
def test_a_cut_is_reviewable_when_the_optional_model_record_is_missing_or_unreadable(
    tmp_path, payload
):
    if payload is not None:
        folder = tmp_path / "derived-decisions"
        folder.mkdir()
        (folder / "thin-polish.private.json").write_text(payload)

    assert read_cut_decisions(tmp_path) == {}


def _record(tmp_path, **record):
    folder = tmp_path / "derived-decisions"
    folder.mkdir()
    (folder / "thin-polish.private.json").write_text(json.dumps({"ran": True} | record))


def test_an_accepted_swap_is_explained_on_the_picture_that_took_the_seat(tmp_path):
    _record(
        tmp_path,
        verdicts={"original": {"state": "weak", "named_by": 1, "why": "Repeated view"}},
        slots=[
            {
                "rule": "vote-weak",
                "story": "S1",
                "replacing": "original",
                "chosen": "newcomer",
                "offered": "4",
                "outcome": "seated",
            }
        ],
        revoked_by_the_fit_check=[],
    )

    decision = read_cut_decisions(tmp_path)["newcomer"]

    assert decision["replaced_asset_id"] == "original"
    assert decision["model_reason"] == "Repeated view"
    assert decision["offered_count"] == 4


def test_a_newcomer_the_fit_check_revoked_leaves_the_original_explained_as_restored(tmp_path):
    _record(
        tmp_path,
        verdicts={"original": {"state": "weak", "named_by": 1, "why": "Repeated view"}},
        slots=[
            {
                "rule": "vote-weak",
                "replacing": "original",
                "chosen": "newcomer",
                "offered": "3",
                "outcome": "seated",
            }
        ],
        revoked_by_the_fit_check=["newcomer"],
    )

    review = read_cut_decisions(tmp_path)

    assert "newcomer" not in review
    assert review["original"]["proposed_asset_id"] == "newcomer"
    assert review["original"]["replacement_outcome"] == "taken back by the fit check"


@pytest.mark.parametrize("seat", ["vote-bad", "gate-refused", "notable"])
def test_a_picture_seated_without_a_named_predecessor_says_which_seat_it_took(tmp_path, seat):
    _record(
        tmp_path,
        verdicts={},
        slots=[{"rule": seat, "replacing": "", "chosen": "newcomer", "outcome": "seated"}],
    )

    decision = read_cut_decisions(tmp_path)["newcomer"]

    assert decision["seat"] == seat
    assert decision["replaced_asset_id"] == ""
