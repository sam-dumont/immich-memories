"""The account owner: a guess a scan makes, and an answer a person gives.

Every person here is invented.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from immich_memories.people.companion import (
    load_document,
    people_entries,
    save_confirmed_relationship,
    save_graph,
    set_owner,
)
from immich_memories.people.graph import Owner, PeopleGraph, PersonNode
from immich_memories.people.owner import confirmed_owner
from immich_memories.people.signatures import PersonEvidence, Tier


def _node(name: str, person_id: str) -> PersonNode:
    return PersonNode(
        evidence=PersonEvidence(
            person_id=person_id,
            name=name,
            count=400,
            active_months=(date(2019, 1, 1),),
            birth_date=None,
        ),
        tier=Tier.INNER,
    )


def _scan(store, owner: Owner | None) -> None:
    graph = PeopleGraph(
        people=(_node("Alex Example", "id-alex"), _node("Sam Sample", "id-sam")),
        owner=owner,
        built_at=datetime(2026, 8, 25, 9, 0, 0),
    )
    save_graph(store, graph)


def _roles(store) -> dict[str, str | None]:
    return {e["name"]: e["confirmed"]["role"] for e in people_entries(load_document(store))}


def test_a_rc5_registry_keeps_its_owner_as_a_guess(store):
    _scan(store, Owner("id-alex", "Alex Example", "inferred"))

    document = load_document(store)
    assert document["owner"]["identified"] == "inferred"
    assert confirmed_owner(document) is None


def test_confirming_the_owner_survives_a_scan_that_guesses_somebody_else(store):
    _scan(store, Owner("id-alex", "Alex Example", "inferred"))

    set_owner(store, "id-sam")
    _scan(store, Owner("id-alex", "Alex Example", "inferred"))

    document = load_document(store)
    assert (document["owner"]["person_id"], document["owner"]["identified"]) == (
        "id-sam",
        "confirmed",
    )
    answer = confirmed_owner(document)
    assert answer is not None and answer.person_id == "id-sam"


def test_nobody_in_this_library_is_an_answer_a_scan_keeps(store):
    _scan(store, Owner("id-alex", "Alex Example", "inferred"))

    set_owner(store, None)
    _scan(store, Owner("id-alex", "Alex Example", "inferred"))

    document = load_document(store)
    assert document["owner"] is None
    answer = confirmed_owner(document)
    assert answer is not None and answer.person_id is None


def test_each_account_has_its_own_owner(store):
    _scan(store, Owner("id-alex", "Alex Example", "inferred"))

    set_owner(store, "id-sam", account="partner")

    document = load_document(store)
    assert confirmed_owner(document) is None
    partner = confirmed_owner(document, "partner")
    assert partner is not None and partner.person_id == "id-sam"
    assert document["owner"]["person_id"] == "id-alex", "the primary's guess is untouched"


def test_somebody_the_registry_does_not_hold_cannot_be_the_owner(store):
    _scan(store, None)

    with pytest.raises(ValueError, match="id-nobody"):
        set_owner(store, "id-nobody")


def test_changing_the_owner_clears_roles_derived_from_the_old_one_and_keeps_typed_ones(store):
    _scan(store, Owner("id-alex", "Alex Example", "inferred"))
    set_owner(store, "id-alex")
    save_confirmed_relationship(store, "id-sam", "partner-of", "id-alex")
    assert _roles(store)["Sam Sample"] == "partner"

    set_owner(store, "id-sam")

    # Sam is the owner now, so the role he held towards Alex was Alex's to give; Alex's own
    # role towards the new owner is re-derived from the reverse edge.
    assert _roles(store) == {"Alex Example": "partner", "Sam Sample": None}


def test_a_role_somebody_typed_stays_when_the_owner_changes(store):
    from immich_memories.people.companion import save_confirmed

    _scan(store, Owner("id-alex", "Alex Example", "inferred"))
    set_owner(store, "id-alex")
    save_confirmed_relationship(store, "id-sam", "partner-of", "id-alex")
    save_confirmed(
        store,
        "id-sam",
        {
            "role": "wife",
            "links": people_entries(load_document(store))[1]["confirmed"]["links"],
            "notes": None,
        },
    )

    set_owner(store, None)

    assert _roles(store)["Sam Sample"] == "wife"
