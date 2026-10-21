"""A moment held back for its place is still a moment the depth fill can deepen (#2772).

A day's event at one place and a stray picture at home make a story of two places, so the event's
place is bounded (`selection.places`). When the bound refused the carrier of the event's biggest
moment, that moment was marked used but never chosen: the depth fill's ladder offered it neither as
an unchosen moment nor as rungs of a chosen one, the film stopped at a handful of shots with most of
its content seconds unspent, and the refused carrier only came back after the fill was over. A rich
track day shipped four shots this way.
"""

from immich_memories.analysis.selection.carriers import CarrierAdmission
from immich_memories.analysis.selection.lookalike import LookAlikeCheck
from immich_memories.analysis.selection.places import place_shares
from immich_memories.analysis.selection.standing import StandingGate
from immich_memories.analysis.stories.shortlist import DepictedChoice
from immich_memories.analysis.stories.slots import PartitionedSlots

SLOTS = 12
# One picture at home in the morning, two short moments at the circuit, then the event itself:
# twelve pictures across an hour.
MOMENTS = {
    "M0": ("Hometown", ["home-0"], 8),
    "M1": ("Circuit", ["arrival-0"], 10),
    "M2": ("Circuit", ["paddock-0"], 11),
    "M3": ("Circuit", [f"race-{n}" for n in range(12)], 12),
}


def _units():
    units = {}
    for moment, (_place, members, hour) in MOMENTS.items():
        for index, asset in enumerate(members):
            units[asset] = (
                "F01",
                {
                    "asset_id": asset,
                    "moment": moment,
                    "taken": f"2030-06-12T{hour:02d}:{5 * index:02d}:00",
                    "favourite": False,
                    "kind": "still",
                    "seconds": 4.0,
                },
            )
    return units


def _place_of(asset: str) -> str:
    return next(place for place, members, _hour in MOMENTS.values() if asset in members)


def _admission():
    unit_by_asset = _units()
    story = {
        "key": "S001",
        "title": "A track day",
        "weight": "minor",
        "gate": "remarkable",
        "seen": {"favourites": 0},
        "purpose": "",
    }
    choices = [
        DepictedChoice(
            key=f"{moment}:cg",
            episode="S001",
            taken=unit_by_asset[members[0]][1]["taken"],
            content="capture group",
            primary=members[0],
            alternatives=list(members[1:]),
        )
        for moment, (_place, members, _hour) in MOMENTS.items()
    ]
    gate = StandingGate(
        lambda _asset: 2,
        line_of=lambda a: f"line for {a}",
        life=lambda _a: False,
        unit_by_asset=unit_by_asset,
        pictures_of={"S001": len(unit_by_asset)},
    )

    def never(*_args, **_kwargs):
        raise AssertionError("the plan asked a model")

    places = place_shares(
        [story],
        {"S001": [unit for _family, unit in unit_by_asset.values()]},
        place_of=_place_of,
        slots=SLOTS,
        journey=False,
    )
    return CarrierAdmission(
        type("Judge", (), {"calls": [], "ask": staticmethod(never)})(),
        stories=[story],
        choices_of={"S001": choices},
        unit_by_asset=unit_by_asset,
        anchor_label={"F01": "A track day"},
        parts=PartitionedSlots(unit_by_asset),
        gate=gate,
        line_of=lambda a: f"line for {a}",
        life=lambda _a: False,
        excluded={},
        kind_marker=lambda _c: "",
        motion_line=None,
        contract="",
        record=lambda _name, _value: None,
        slots=SLOTS,
        calls={"pick_calls": 0},
        mechanical_picks=True,
        # Frames five minutes apart never look alike here: this test is about the ledger.
        lookalike=LookAlikeCheck(lambda _candidate, _keeper: False, slots=SLOTS),
        places=places,
        place_of=_place_of,
        content_budget_seconds=40.0,
    )


def test_a_moment_waiting_for_its_place_is_deepened_when_the_film_is_short():
    admission = _admission()

    admission.run()

    race = [c for c in admission.carriers if c["asset_id"].startswith("race-")]
    assert len(race) >= 5
    assert sum(float(c["seconds"]) for c in admission.carriers) >= 40.0 * 0.85
