"""A sparse week's quality pick (#2048) becomes its carrier, through the real admission.

`read_story` chooses a week's best picture once, over its whole pool, and marks the week
`funded_by="quality"` with that choice. `CarrierAdmission` must surface exactly that
picture as the week's carrier without asking the reader a fresh question — and must
never force a picture the standing gate has refused into the primary slot just because
`read_story`'s own hard filters did not see that refusal coming (#2048 review, point B).
"""

from immich_memories.analysis.editorial_story_carriers import CarrierAdmission
from immich_memories.analysis.editorial_story_shortlist import DepictedChoice
from immich_memories.analysis.editorial_story_slots import PartitionedSlots
from immich_memories.analysis.editorial_story_standing import StandingGate


def _unit(asset, *, taken, favourite=False):
    return (
        "F01",
        {
            "asset_id": asset,
            "moment": "m1",
            "taken": taken,
            "favourite": favourite,
            "kind": "still",
            "seconds": 4.0,
        },
    )


def _run(unit_by_asset, score_of, quality_asset_id):
    story = {
        "key": "S001",
        "title": "A quiet week",
        "weight": "glimpse",
        "gate": "background",
        "seen": {"favourites": 0},
        "purpose": "",
        "funded_by": "quality",
        "quality_asset_id": quality_asset_id,
    }
    choice = DepictedChoice(
        "m1:cg",
        "S001",
        next(iter(unit_by_asset.values()))[1]["taken"],
        "capture group",
        primary=next(iter(unit_by_asset)),
        alternatives=[a for a in unit_by_asset if a != next(iter(unit_by_asset))],
    )
    admission = CarrierAdmission(
        None,
        stories=[story],
        choices_of={"S001": [choice]},
        unit_by_asset=unit_by_asset,
        anchor_label={"F01": "A quiet week"},
        parts=PartitionedSlots(unit_by_asset),
        gate=StandingGate(
            score_of,
            line_of=lambda a: f"line for {a}",
            life=lambda _a: True,
            unit_by_asset=unit_by_asset,
            pictures_of={"S001": len(unit_by_asset)},
        ),
        line_of=lambda a: f"line for {a}",
        life=lambda _a: True,
        excluded={},
        kind_marker=lambda _c: "",
        motion_line=None,
        contract="A quiet week",
        record=lambda *_a, **_kw: None,
        slots=1,
        calls={"pick_calls": 0},
        mechanical_picks=True,
    )
    admission.run()
    return admission.carriers


def test_the_quality_pick_becomes_the_carrier_over_the_ordinary_favourite_first_order():
    unit_by_asset = {
        "obvious": _unit("obvious", taken="2024-06-01T10:00:00", favourite=True),
        "quality_pick": _unit("quality_pick", taken="2024-06-01T10:01:00"),
    }

    carriers = _run(unit_by_asset, score_of=lambda _a: 2, quality_asset_id="quality_pick")

    assert [c["asset_id"] for c in carriers] == ["quality_pick"]


def test_the_week_goes_short_when_the_quality_pick_fails_the_standing_gate():
    """The hard filters `read_story` ran (sharpness, standing, never a screenshot) are not
    the carrier gate: if the gate refuses the chosen asset for a reason of its own (an
    owner-cleared hold, a missing context), the week goes short rather than forcing a
    gate-failed picture into the primary slot."""
    unit_by_asset = {
        "obvious": _unit("obvious", taken="2024-06-01T10:00:00", favourite=True),
        "refused": _unit("refused", taken="2024-06-01T10:01:00"),
    }

    carriers = _run(
        unit_by_asset,
        score_of=lambda a: 0 if a == "refused" else 2,
        quality_asset_id="refused",
    )

    assert carriers == []
