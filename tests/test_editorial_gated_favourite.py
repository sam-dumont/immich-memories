"""A moment whose favourite the audience holds is dropped whole: nothing else stands for it."""

from __future__ import annotations

from immich_memories.analysis import editorial_shareability as share
from immich_memories.analysis.editorial_cut_invariants import FinishedCut, cut_violations
from immich_memories.analysis.editorial_picture_admission import PictureAdmission
from immich_memories.analysis.favourite_law import favourites_by_moment
from tests.test_editorial_thin_gates import Audience, Standing, shot


def _admission(units, held, hashes=None):
    admission = PictureAdmission(
        standing=Standing({}),
        audience=Audience(dict.fromkeys(held, "do_not_show")),
        thumbnail_hash=hashes.get if hashes else None,
        moment_favourites=favourites_by_moment(units),
    )
    return lambda row, cut: admission.admits(row, cut=cut, tier_of={}) is None


def _gate(carriers, offers, units, held, hashes=None):
    return share.apply_gate(
        carriers,
        verdict_of=lambda unit: "do_not_show" if unit["asset_id"] in held else "share",
        pool_for=lambda carrier: offers.get(carrier["asset_id"], []),
        admits=_admission(units, held, hashes),
    )


def _cut(kept, units, held):
    return FinishedCut(
        carriers=kept,
        units={u["asset_id"]: u for u in units},
        verdict_of=lambda a: "do_not_show" if a in held else "share",
    )


def test_a_moment_whose_only_favourite_is_held_ships_nothing_and_another_moment_fills_it():
    starred = shot("starred", moment="M1", favourite=True, taken="2024-02-01T09:00:00")
    beside = shot("beside", moment="M1", taken="2024-02-01T09:01:00")
    elsewhere = shot("elsewhere", moment="M3", taken="2024-02-01T11:00:00")
    other = shot("other", moment="M2", taken="2024-02-01T10:00:00")
    units = [starred, beside, elsewhere, other]

    kept, _log = _gate([starred, other], {"starred": [beside, elsewhere]}, units, held={"starred"})

    assert [c["asset_id"] for c in kept] == ["other", "elsewhere"]
    assert cut_violations(_cut(kept, units, {"starred"})) == []


def test_a_moment_with_two_favourites_ships_the_one_the_audience_allows():
    held = shot("held", moment="M1", favourite=True, taken="2024-02-01T09:00:00")
    beside = shot("beside", moment="M1", taken="2024-02-01T09:01:00")
    twin = shot("twin", moment="M1", favourite=True, taken="2024-02-01T09:02:00")
    units = [held, beside, twin]

    kept, _log = _gate([held], {"held": [beside, twin]}, units, held={"held"})

    assert [c["asset_id"] for c in kept] == ["twin"]
    assert cut_violations(_cut(kept, units, {"held"})) == []


def test_a_neighbour_never_stands_in_when_the_allowed_favourite_repeats_another_shot():
    """The allowed favourite is refused as a look-alike of the next moment's shot. Its plain
    neighbour taking the slot is what the invariant exists to catch; the moment goes instead."""
    held = shot("held", moment="M1", favourite=True, taken="2024-02-01T09:00:00")
    twin = shot("twin", moment="M1", favourite=True, taken="2024-02-01T09:02:00")
    beside = shot("beside", moment="M1", taken="2024-02-01T09:03:00")
    next_door = shot("next-door", moment="M2", favourite=True, taken="2024-02-01T09:30:00")
    units = [held, twin, beside, next_door]
    hashes = {"twin": "0" * 16, "next-door": "0" * 16, "beside": "f" * 16, "held": "0f" * 8}

    kept, _log = _gate(
        [held, next_door], {"held": [twin, beside]}, units, held={"held"}, hashes=hashes
    )

    assert [c["asset_id"] for c in kept] == ["next-door"]
    assert cut_violations(_cut(kept, units, {"held"})) == []
    stood_in = _cut([beside, next_door], units, {"held"})
    assert [(v.invariant, v.subject) for v in cut_violations(stood_in)] == [
        ("favourite_wins_its_moment", "beside")
    ]
