"""A reader that never answers a story's pick leaves the story the moments the rules keep.

Two films died on one unreadable pick (#1467). The no-model film picks a story's moments
without asking anybody; a model film whose reader gives nothing readable for a story takes
exactly those moments for it instead of ending.
"""

from immich_memories.analysis.editorial_story_carriers import CarrierAdmission
from immich_memories.analysis.editorial_story_shortlist import DepictedChoice
from immich_memories.analysis.editorial_story_slots import PartitionedSlots
from immich_memories.analysis.editorial_story_standing import StandingGate

# Three moments of one afternoon, far enough apart to share a film. Only strangers are in
# the crowd, so the rules take it last.
MOMENTS = {"harbour": "10:00", "crowd": "10:20", "picnic": "10:40"}


class UnreadableReader:
    # WHY: the model boundary. It answers every pick, and its repair, with prose where the
    # JSON object belongs: the answer that ended a real film.
    def __init__(self):
        self.calls = []

    def ask(self, stage, _prompt, **_kwargs):
        self.calls.append(stage)
        return "The picnic, clearly: everybody is in it."


def _run(judge, *, mechanical):
    unit_by_asset = {
        asset: (
            "F01",
            {
                "asset_id": asset,
                "moment": asset,
                "taken": f"2022-08-13T{at}:00",
                "favourite": False,
                "kind": "still",
                "seconds": 4.0,
            },
        )
        for asset, at in MOMENTS.items()
    }
    story = {
        "key": "S001",
        "title": "An afternoon out",
        "weight": "minor",
        "gate": "remarkable",
        "seen": {"favourites": 0},
        "purpose": "",
    }
    records = {}
    admission = CarrierAdmission(
        judge,
        stories=[story],
        choices_of={
            "S001": [
                DepictedChoice(f"{asset}:cg", "S001", unit["taken"], "capture group", asset)
                for asset, (_family, unit) in unit_by_asset.items()
            ]
        },
        unit_by_asset=unit_by_asset,
        anchor_label={"F01": "An afternoon out"},
        parts=PartitionedSlots(unit_by_asset),
        gate=StandingGate(
            lambda _asset: 2,
            line_of=lambda a: f"line for {a}",
            life=lambda _a: True,
            unit_by_asset=unit_by_asset,
            pictures_of={"S001": len(MOMENTS)},
        ),
        line_of=lambda a: f"line for {a}",
        life=lambda _a: True,
        excluded={},
        kind_marker=lambda _c: "",
        motion_line=None,
        contract="Show the afternoon",
        record=records.__setitem__,
        slots=1,
        calls={"pick_calls": 0},
        mechanical_picks=mechanical,
        strangers_only=lambda asset: asset == "crowd",
    )
    admission.run()
    return [carrier["asset_id"] for carrier in admission.carriers], records


def test_a_story_whose_reader_never_answers_keeps_the_moments_the_rules_keep():
    by_rules, _records = _run(None, mechanical=True)
    reader = UnreadableReader()

    by_model, records = _run(reader, mechanical=False)

    assert by_model == by_rules == ["picnic"]
    assert reader.calls
    votes = records["story-pick-S001"]["vote_records"]
    assert {vote["review_stage"] for vote in votes} == {"pick-rules-fallback"}
