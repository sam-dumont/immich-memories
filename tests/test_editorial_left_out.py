"""Every picture the final cut leaves out carries the reason the plan had (#2135)."""

from immich_memories.analysis.editorial_left_out import final_cut_notes


def _plan(**fields):
    return {"carriers": [], "cut_carriers": [], "shareability": {}} | fields


def test_a_picture_the_family_viewing_check_held_says_so():
    plan = _plan(
        shareability={
            "audience": "shareable",
            "verdicts": {
                "held": {
                    "verdict": "family_only",
                    "finding": "unread_private_activity",
                    "why": "no detector head objected, but no description was read to clear it",
                },
                "cleared": {"verdict": "share", "finding": "clean_evidence"},
            },
        }
    )

    notes = final_cut_notes(plan, ["held"])

    assert notes == {
        "held": "the family-viewing check held it from a shareable film: no detector head "
        "objected, but no description was read to clear it"
    }


def test_a_picture_a_later_pass_cut_names_that_pass_reason():
    plan = _plan(cut_carriers=[{"asset_id": "repeat", "reason": "Same scene as an earlier shot"}])

    assert final_cut_notes(plan, ["repeat"]) == {"repeat": "Same scene as an earlier shot"}


def test_every_other_picture_left_out_still_has_a_reason():
    plan = _plan(carriers=[{"asset_id": "shipped"}])

    assert final_cut_notes(plan, ["unused"]) == {
        "unused": "kept by every pass, not used in the plan"
    }


def test_an_empty_cut_says_the_check_held_every_shot_it_chose():
    plan = _plan(
        shareability={
            "audience": "shareable",
            "verdicts": {"held": {"verdict": "family_only", "finding": "strict_sharing"}},
            "tightened": [{"asset_id": "held", "verdict": "family_only"}],
            "dropped": [{"asset_id": "held", "verdict": "family_only"}],
        }
    )

    notes = final_cut_notes(plan, ["held", "unused"])

    assert notes["held"] == "the family-viewing check held it from a shareable film: strict_sharing"
    assert notes["unused"] == (
        "not used: the family-viewing check held back every shot this shareable film chose"
    )


def test_a_finished_run_names_why_each_unused_picture_is_out(tmp_path):
    from datetime import UTC, datetime, timedelta

    from immich_memories.operations.candidate_fates import read_trace
    from tests.test_editorial_selected_preparation import _film
    from tests.test_editorial_source_route import photo

    first = datetime(2024, 2, 1, 12, tzinfo=UTC)
    sources = [photo(f"picture-{n:02}", at=first + timedelta(days=n)) for n in range(24)]
    for asset in sources:
        asset.is_favorite = True

    selected, _ = _film(tmp_path, sources, tier="basic")

    (trace_file,) = (tmp_path / "artifacts").glob("**/selection-trace.private.json")
    trace = read_trace(trace_file.parent)
    assert trace is not None
    unused = {asset.id for asset in sources} - selected
    assert unused
    assert all(trace.story_of(asset_id).reason for asset_id in unused)
