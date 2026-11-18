"""The family tree the People page draws, read off the confirmed relationships (#2797).

Every test builds a registry document the way the page writes one (both directions of each
answer) and reads the tree the page gets: who is in it, which row they sit on, where along
the row, which families hang from which parents, and how many people were left out.
"""

from __future__ import annotations

import random
from typing import Any

import pytest

from immich_memories.people.family_tree import FamilyTree, family_tree
from immich_memories.people.family_tree_layout import BAR_GAP
from immich_memories.people.relationships import reciprocal_kind
from tests.e2e.family_tree_household import TWO_FAMILIES, TWO_FAMILIES_BORN


def _document(
    relationships: tuple[tuple[str, str, str], ...],
    *,
    people: tuple[str, ...] = (),
    born: dict[str, str | None] | None = None,
    owner: str | None = None,
    declined: tuple[tuple[str, str, str], ...] = (),
) -> dict[str, Any]:
    """A registry where `<person> is <kind> <other>`, written on both people like the page does."""
    names = list(dict.fromkeys([*people, *(n for r in relationships for n in (r[0], r[2]))]))
    links: dict[str, list[dict[str, str]]] = {name: [] for name in names}
    for rows, decision in ((relationships, "confirmed"), (declined, "rejected")):
        for name, kind, other in rows:
            back = reciprocal_kind(kind)
            links[name].append({"kind": kind, "with": f"id-{other}", "decision": decision})
            links[other].append({"kind": back, "with": f"id-{name}", "decision": decision})
    document: dict[str, Any] = {
        "version": 1,
        "people": [
            {
                "ids": [f"id-{name}"],
                "name": name,
                "birth_date": (born or {}).get(name),
                "confirmed": {"role": None, "links": links[name], "notes": None},
            }
            for name in names
        ],
    }
    if owner:
        document["owner"] = {"person_id": f"id-{owner}", "name": owner, "identified": "confirmed"}
    return document


def _x(tree: FamilyTree) -> dict[str, float]:
    return {person.name: person.x for person in tree.people}


def _row(tree: FamilyTree) -> dict[str, int]:
    return {person.name: person.generation for person in tree.people}


def _family(tree: FamilyTree, *children: str):
    wanted = {f"id-{child}" for child in children}
    return next(f for f in tree.families if wanted <= {c.person_id for c in f.children})


def _knot(tree: FamilyTree, family) -> float:
    x = {person.person_id: person.x for person in tree.people}
    ids = family.parents or tuple(child.person_id for child in family.children)
    return sum(x[i] for i in ids) / len(ids)


def _no_overlap(tree: FamilyTree) -> None:
    rows: dict[int, list[float]] = {}
    for person in tree.people:
        rows.setdefault(person.generation, []).append(person.x)
    for xs in rows.values():
        xs.sort()
        assert all(b - a >= 1 - 1e-9 for a, b in zip(xs, xs[1:], strict=False)), xs


# The household the e2e test and the docs screenshot draw: two grandparents, their two
# children, one married to someone whose parents aren't in the tree but whose sibling is.
_HOUSEHOLD = (
    ("Pat", "partner-of", "Lou"),
    ("Robin", "child-of", "Pat"),
    ("Robin", "child-of", "Lou"),
    ("Sasha", "child-of", "Pat"),
    ("Sasha", "child-of", "Lou"),
    ("Charlie", "partner-of", "Robin"),
    ("Charlie", "sibling-of", "Mo"),
    ("Kit", "child-of", "Robin"),
    ("Kit", "child-of", "Charlie"),
    ("Remy", "child-of", "Robin"),
    ("Remy", "child-of", "Charlie"),
    ("Nico", "child-of", "Sasha"),
    ("Jo", "friend-of", "Kit"),
)
_BORN = {"Robin": "1987-03-14", "Sasha": "1989-12-12", "Kit": "2020-07-05", "Remy": "2024-02-10"}


def test_a_couple_sits_side_by_side_with_their_children_one_row_down_under_their_midpoint():
    tree = family_tree(
        _document(
            (
                ("Ana", "partner-of", "Luc"),
                ("Ana", "parent-of", "Eli"),
                ("Luc", "parent-of", "Eli"),
                ("Ana", "parent-of", "Zoe"),
                ("Luc", "parent-of", "Zoe"),
            ),
            born={"Eli": "2015-01-01", "Zoe": "2018-01-01"},
        )
    )

    assert _row(tree) == {"Ana": 0, "Luc": 0, "Eli": 1, "Zoe": 1}
    x = _x(tree)
    assert abs(x["Ana"] - x["Luc"]) == pytest.approx(1)
    assert {frozenset(couple) for couple in tree.couples} == {frozenset({"id-Ana", "id-Luc"})}
    family = _family(tree, "Eli", "Zoe")
    assert set(family.parents) == {"id-Ana", "id-Luc"}
    assert [c.person_id for c in family.children] == ["id-Eli", "id-Zoe"], "eldest first"
    assert (x["Eli"] + x["Zoe"]) / 2 == pytest.approx(_knot(tree, family))
    assert min(x.values()) == 0


def test_the_household_reads_as_three_generations_with_married_children_facing_each_other():
    tree = family_tree(_document(_HOUSEHOLD, born=_BORN, owner="Robin"))

    assert _row(tree) == {
        "Pat": 0,
        "Lou": 0,
        "Robin": 1,
        "Sasha": 1,
        "Charlie": 1,
        "Mo": 1,
        "Kit": 2,
        "Remy": 2,
        "Nico": 2,
    }
    x = _x(tree)
    # Robin sits on the side of her family that faces Charlie's, so no line crosses.
    middle_row = sorted(("Sasha", "Robin", "Charlie", "Mo"), key=x.__getitem__)
    assert middle_row in (["Sasha", "Robin", "Charlie", "Mo"], ["Mo", "Charlie", "Robin", "Sasha"])
    assert abs(x["Robin"] - x["Charlie"]) == pytest.approx(1)
    assert x["Kit"] < x["Remy"], "eldest first"
    assert (x["Nico"] > x["Remy"]) == (x["Sasha"] > x["Robin"]), "Nico on his mother's side"
    for children in (("Kit", "Remy"), ("Robin", "Sasha")):
        family = _family(tree, *children)
        middle = sum(x[c] for c in children) / len(children)
        assert abs(middle - _knot(tree, family)) < 0.75, (children, middle)
    _no_overlap(tree)
    assert [p.name for p in tree.people if p.owner] == ["Robin"]
    born = {p.name: p.birth_year for p in tree.people}
    assert born["Robin"] == 1987 and born["Pat"] is None


def test_siblings_whose_parents_are_not_in_the_tree_hang_from_a_knot_of_their_own():
    tree = family_tree(_document((("Ana", "sibling-of", "Luc"), ("Ana", "sibling-of", "Eli"))))

    family = _family(tree, "Ana", "Luc", "Eli")
    assert family.parents == ()
    assert all(child.through_sibling for child in family.children)
    assert set(_row(tree).values()) == {0}


def test_a_sibling_with_no_recorded_parent_joins_the_family_drawn_through_the_sibling():
    tree = family_tree(_document((("Ana", "parent-of", "Eli"), ("Eli", "sibling-of", "Zoe"))))

    family = _family(tree, "Eli", "Zoe")
    assert family.parents == ("id-Ana",)
    through = {c.person_id: c.through_sibling for c in family.children}
    assert through == {"id-Eli": False, "id-Zoe": True}
    assert _row(tree) == {"Ana": 0, "Eli": 1, "Zoe": 1}


def test_people_with_no_family_link_are_left_out_and_counted():
    tree = family_tree(_document(_HOUSEHOLD, people=("Alex",), born=_BORN))

    names = {person.name for person in tree.people}
    assert "Jo" not in names and "Alex" not in names
    assert tree.left_out == 2


def test_the_suggestions_the_tree_implies_come_as_dotted_ties_never_as_drawn_ones():
    tree = family_tree(
        _document(
            (("Ana", "partner-of", "Luc"), ("Ana", "parent-of", "Eli"), ("Ana", "parent-of", "Zoe"))
        )
    )

    family = _family(tree, "Eli", "Zoe")
    assert family.parents == ("id-Ana",), "Luc is only suggested as a parent"
    shown = {(s.source, s.kind, s.target) for s in tree.suggestions}
    # One line per pair, said from the parent's side; Eli and Zoe already share a knot.
    assert shown == {("id-Luc", "parent-of", "id-Eli"), ("id-Luc", "parent-of", "id-Zoe")}


def test_a_declined_suggestion_is_not_offered_on_the_tree():
    tree = family_tree(
        _document(
            (("Ana", "partner-of", "Luc"), ("Ana", "parent-of", "Eli")),
            declined=(("Luc", "parent-of", "Eli"),),
        )
    )

    assert tree.suggestions == ()


def test_separate_families_sit_side_by_side_the_owner_s_first():
    tree = family_tree(
        _document(
            (
                ("Ana", "partner-of", "Luc"),
                ("Eli", "sibling-of", "Zoe"),
                ("Eli", "sibling-of", "Max"),
            ),
            owner="Eli",
        )
    )

    x = _x(tree)
    assert max(x["Eli"], x["Zoe"], x["Max"]) < min(x["Ana"], x["Luc"])
    _no_overlap(tree)


def test_a_contradiction_still_draws_everybody_once():
    tree = family_tree(
        _document(
            (
                ("Ana", "parent-of", "Luc"),
                ("Luc", "parent-of", "Eli"),
                ("Eli", "parent-of", "Ana"),
                ("Ana", "partner-of", "Eli"),
            )
        )
    )

    assert sorted(p.name for p in tree.people) == ["Ana", "Eli", "Luc"]
    _no_overlap(tree)


def test_the_same_registry_draws_the_same_tree_whatever_order_it_was_written_in():
    document = _document(_HOUSEHOLD, born=_BORN, owner="Robin")
    shuffled = {**document, "people": list(document["people"])}
    random.Random(7).shuffle(shuffled["people"])

    assert family_tree(shuffled) == family_tree(document)


def test_an_empty_registry_is_an_empty_tree():
    tree = family_tree({"version": 1, "people": []})

    assert tree.people == () and tree.families == () and tree.left_out == 0


def _row_order(tree: FamilyTree, generation: int) -> list[str]:
    return [p.name for p in sorted(tree.people, key=lambda p: p.x) if p.generation == generation]


def _children(tree: FamilyTree, family) -> list[str]:
    names = {person.person_id: person.name for person in tree.people}
    return [names[child.person_id] for child in family.children]


def _bars(tree: FamilyTree) -> list[tuple[int, int, float, float, Any]]:
    """(children's row, lane, left end, right end, family) of every family's line to its children:
    the line runs from the knot over the parents to the outermost child."""
    x = {person.person_id: person.x for person in tree.people}
    row = {person.person_id: person.generation for person in tree.people}
    bars = []
    for family in tree.families:
        xs = [_knot(tree, family), *(x[c.person_id] for c in family.children)]
        bars.append(
            (min(row[c.person_id] for c in family.children), family.lane, min(xs), max(xs), family)
        )
    return bars


def _bars_stay_apart(tree: FamilyTree, *, drops_cross: bool = False) -> None:
    """No two families' lines meet: on one height they keep a gap. Unless `drops_cross`, a
    child's drop line also passes no other family's line drawn below its own."""
    x = {person.person_id: person.x for person in tree.people}
    bars = _bars(tree)
    for row, lane, left, right, family in bars:
        for other_row, other_lane, other_left, other_right, other in bars:
            if other is family or other_row != row:
                continue
            if other_lane == lane:
                assert other_right < left - BAR_GAP or right < other_left - BAR_GAP, (
                    _children(tree, family),
                    _children(tree, other),
                )
            if other_lane < lane and not drops_cross:
                assert not any(
                    other_left <= x[c.person_id] <= other_right for c in family.children
                ), (_children(tree, family), _children(tree, other))


def test_two_families_joined_by_a_couple_each_keep_their_children_together_facing_each_other():
    tree = family_tree(_document(TWO_FAMILIES, born=TWO_FAMILIES_BORN, owner="Sam"))

    row = _row_order(tree, 2)
    p_side, q_side = row[: row.index("Sam") + 1], row[row.index("Kit") :]
    if row.index("Kit") < row.index("Sam"):
        p_side, q_side = row[row.index("Sam") :][::-1], row[: row.index("Kit") + 1][::-1]
    # Sam's family on one side of the couple, Kit's on the other, each with their married-in
    # partners next to their spouse on the outside.
    assert p_side == ["Jo", "Robin", "Sasha", "Sam"]
    assert q_side == ["Kit", "Mia", "Max"]
    assert set(_row_order(tree, 1)) == {"Pat", "Lou", "Quinn", "Dale", "Ari", "Bo"}
    _no_overlap(tree)


def test_each_family_hangs_its_children_from_its_own_line():
    tree = family_tree(_document(TWO_FAMILIES, born=TWO_FAMILIES_BORN, owner="Sam"))

    for children in (("Sasha", "Sam", "Robin"), ("Kit", "Mia"), ("Ada", "Ben"), ("Dee", "Gus")):
        family = _family(tree, *children)
        row = _row_order(tree, _row(tree)[children[0]])
        own = [row.index(name) for name in _children(tree, family)]
        between = row[min(own) : max(own) + 1]
        assert set(between) <= set(_children(tree, family)) | {"Jo", "Max"}, between
    _bars_stay_apart(tree)


def test_families_married_into_each_other_twice_draw_their_lines_at_different_heights():
    # Two pairs of siblings married across: no order keeps both families' children apart.
    tree = family_tree(
        _document(
            (
                ("Pat", "partner-of", "Lou"),
                ("Quinn", "partner-of", "Dale"),
                *((c, "child-of", p) for c in ("Ana", "Eli", "Ivy") for p in ("Pat", "Lou")),
                *((c, "child-of", p) for c in ("Kit", "Zoe", "Uma") for p in ("Quinn", "Dale")),
                ("Ana", "partner-of", "Kit"),
                ("Eli", "partner-of", "Zoe"),
            )
        )
    )

    first, second = _family(tree, "Ana", "Eli"), _family(tree, "Kit", "Zoe")
    assert first.lane != second.lane
    # Each couple still stands at the seam, so one family's drop lines cross the other's line.
    _bars_stay_apart(tree, drops_cross=True)
    _no_overlap(tree)
