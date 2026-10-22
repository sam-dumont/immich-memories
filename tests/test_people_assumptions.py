"""Normative family closure stays derived, explainable, and read-only."""

from __future__ import annotations

import copy

from immich_memories.people.assumptions import family_assumptions


def _document(
    *facts: tuple[str, str, str], declined: tuple[tuple[str, str, str], ...] = ()
) -> dict:
    answers = [(fact, "confirmed") for fact in facts] + [(fact, "rejected") for fact in declined]
    ids = sorted(
        {person_id for (source, _, target), _ in answers for person_id in (source, target)}
    )
    links = {person_id: [] for person_id in ids}
    for (source_id, kind, target_id), decision in answers:
        links[source_id].append({"kind": kind, "with": target_id, "decision": decision})
    return {
        "people": [
            {
                "ids": [person_id],
                "name": person_id.title(),
                "confirmed": {"role": None, "links": links[person_id], "notes": None},
            }
            for person_id in ids
        ]
    }


def _kinds(document: dict) -> set[tuple[str, str, str]]:
    return {
        (assumption.source_id, assumption.kind, assumption.target_id)
        for assumption in family_assumptions(document)
    }


def test_a_confirmed_sibling_of_a_parent_is_derived_as_aunt_or_uncle_not_parent():
    document = _document(
        ("alex", "sibling-of", "robin"),
        ("robin", "parent-of", "casey"),
    )

    found = _kinds(document)

    assert ("alex", "aunt-or-uncle-of", "casey") in found
    assert ("alex", "parent-of", "casey") not in found


def test_children_with_two_shared_parents_get_one_sibling_proposal_through_one_parent():
    document = _document(
        ("alex", "parent-of", "casey"),
        ("alex", "parent-of", "devon"),
        ("robin", "parent-of", "casey"),
        ("robin", "parent-of", "devon"),
    )

    siblings = [
        assumption for assumption in family_assumptions(document) if assumption.kind == "sibling-of"
    ]

    assert len(siblings) == 1
    assert len(siblings[0].evidence) == 2


def test_children_of_confirmed_siblings_are_derived_as_cousins():
    document = _document(
        ("alex", "sibling-of", "robin"),
        ("alex", "parent-of", "casey"),
        ("robin", "parent-of", "devon"),
    )

    assert ("casey", "cousin-of", "devon") in _kinds(document)


def test_a_partners_parent_and_sibling_are_derived_as_in_laws():
    document = _document(
        ("alex", "partner-of", "robin"),
        ("pat", "parent-of", "robin"),
        ("robin", "sibling-of", "taylor"),
    )

    found = _kinds(document)

    assert ("pat", "parent-in-law-of", "alex") in found
    assert ("alex", "sibling-in-law-of", "taylor") in found


def test_shared_parent_provenance_uses_real_parent_steps_not_a_fake_sibling_fact():
    document = _document(
        ("pat", "parent-of", "alex"),
        ("pat", "parent-of", "robin"),
        ("robin", "parent-of", "casey"),
    )

    assumption = next(
        item
        for item in family_assumptions(document)
        if (item.source_id, item.kind, item.target_id) == ("alex", "aunt-or-uncle-of", "casey")
    )

    assert {step.kind for step in assumption.evidence} == {"parent-of"}
    assert len(assumption.evidence) == 3


def test_closure_never_changes_input_or_reproposes_an_already_confirmed_pair():
    document = _document(
        ("alex", "sibling-of", "robin"),
        ("robin", "parent-of", "casey"),
        ("alex", "uncle-of", "casey"),
    )
    before = copy.deepcopy(document)

    found = family_assumptions(document)

    assert document == before
    assert all(
        frozenset((assumption.source_id, assumption.target_id)) != frozenset(("alex", "casey"))
        for assumption in found
    )


def test_a_siblings_sibling_reaches_their_children_as_nieces_and_nephews():
    document = _document(
        ("alex", "sibling-of", "robin"),
        ("robin", "sibling-of", "sam"),
        ("sam", "parent-of", "casey"),
    )

    found = _kinds(document)

    assert ("alex", "sibling-of", "sam") in found
    assert ("alex", "aunt-or-uncle-of", "casey") in found


def test_a_declined_relationship_is_never_proposed_or_built_on():
    document = _document(
        ("alex", "sibling-of", "robin"),
        ("robin", "sibling-of", "sam"),
        ("sam", "parent-of", "casey"),
        declined=(("alex", "sibling-of", "sam"),),
    )

    found = _kinds(document)

    assert ("alex", "sibling-of", "sam") not in found
    assert ("sam", "sibling-of", "alex") not in found
