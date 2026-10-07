"""A detected link is a question, and answering it names the relationship once.

Every person here is invented.
"""

from __future__ import annotations

from typing import Any

from immich_memories.people.companion import load_document, people_entries
from immich_memories.people.context import load_people_prompt_context
from immich_memories.people.editor import (
    add_relationship,
    load_people,
    save_person,
)
from tests.people_registry_seed import seed_people


def _entry(
    name: str, person_id: str, other: str, *, confirmed_links: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    return {
        "ids": [person_id],
        "name": name,
        "birth_date": None,
        "inferred": {
            "tier": "inner",
            "counts_reliable": True,
            "evidence": {"count": 300},
            "links": [
                {"kind": "tight-dyad", "with": other, "confidence": 0.8, "via": "co-occurrence"}
            ],
        },
        "confirmed": {"role": None, "links": confirmed_links or [], "notes": None},
    }


def _pair(*, ana_links=None, luc_links=None):
    return seed_people(
        {
            "version": 1,
            "people": [
                _entry("Ana Example", "id-ana", "id-luc", confirmed_links=ana_links),
                _entry("Luc Sample", "id-luc", "id-ana", confirmed_links=luc_links),
            ],
        }
    )


def _rows(store, name):
    person = next(p for p in load_people(store) if p.name == name)
    return [(link.kind, link.status) for link in person.links]


def test_a_detected_link_is_one_open_question_per_person():
    store = _pair()

    assert _rows(store, "Ana Example") == [("tight-dyad", "detected")]


def test_naming_it_writes_both_sides_and_leaves_one_row_each():
    store = _pair()

    add_relationship(store, "id-ana", "parent-of", "id-luc")

    assert _rows(store, "Ana Example") == [("parent-of", "named")]
    assert _rows(store, "Luc Sample") == [("child-of", "named")]


def test_a_link_confirmed_in_rc5_stays_linked_but_not_named_on_both_sides():
    store = _pair(ana_links=[{"kind": "tight-dyad", "with": "id-luc", "decision": "confirmed"}])

    assert _rows(store, "Ana Example") == [("tight-dyad", "unnamed")]
    assert _rows(store, "Luc Sample") == [("tight-dyad", "unnamed")]


def test_viewing_an_unnamed_link_writes_nothing_on_the_side_that_never_confirmed_it():
    store = _pair(ana_links=[{"kind": "tight-dyad", "with": "id-luc", "decision": "confirmed"}])

    save_person(store, next(p for p in load_people(store) if p.name == "Luc Sample"))

    luc = next(e for e in people_entries(load_document(store)) if e["name"] == "Luc Sample")
    assert luc["confirmed"]["links"] == []


def test_naming_an_unnamed_link_drops_the_placeholder_from_the_store():
    store = _pair(ana_links=[{"kind": "tight-dyad", "with": "id-luc", "decision": "confirmed"}])

    add_relationship(store, "id-luc", "partner-of", "id-ana")

    kinds = [
        link["kind"]
        for entry in people_entries(load_document(store))
        for link in entry["confirmed"]["links"]
    ]
    assert sorted(kinds) == ["partner-of", "partner-of"]
    assert _rows(store, "Ana Example") == [("partner-of", "named")]


def test_no_rescan_brings_back_the_link_for_an_answered_pair():
    from datetime import date, datetime

    from immich_memories.people.companion import save_graph
    from immich_memories.people.graph import PeopleGraph, PersonNode
    from immich_memories.people.signatures import Link, LinkKind, PersonEvidence, Tier

    store = _pair()
    add_relationship(store, "id-ana", "parent-of", "id-luc")

    def node(name, person_id, other):
        evidence = PersonEvidence(person_id, name, 300, (date(2019, 1, 1),))
        link = Link(LinkKind.TIGHT_DYAD, person_id, other, 0.8, "curve-pairing")
        return PersonNode(evidence=evidence, tier=Tier.INNER, links=(link,))

    save_graph(
        store,
        PeopleGraph(
            (node("Ana Example", "id-ana", "id-luc"), node("Luc Sample", "id-luc", "id-ana")),
            None,
            datetime(2026, 9, 1),
        ),
    )

    assert _rows(store, "Ana Example") == [("parent-of", "named")]
    assert _rows(store, "Luc Sample") == [("child-of", "named")]


def test_a_no_on_one_side_closes_the_question_on_the_other():
    store = _pair(ana_links=[{"kind": "tight-dyad", "with": "id-luc", "decision": "rejected"}])

    assert _rows(store, "Ana Example") == [("tight-dyad", "rejected")]
    assert _rows(store, "Luc Sample") == []


def test_a_placeholder_is_not_a_relationship_kind_in_the_people_context():
    store = _pair(ana_links=[{"kind": "tight-dyad", "with": "id-luc", "decision": "confirmed"}])

    context = load_people_prompt_context(store)

    assert context["id-ana"].relationships == ()
