"""The editor offers what the tree implies, and keeps only what somebody accepts (#2795).

Every person here is invented.
"""

from __future__ import annotations

from immich_memories.config.models.editorial import EditorialConfig
from immich_memories.db import Store
from immich_memories.free_text.library import read_library
from immich_memories.people.companion import load_document, people_entries
from immich_memories.people.editor import (
    SUGGESTED,
    accept_suggestions,
    add_relationship,
    answer_person,
    load_people,
    remove_relationship,
)
from tests.people_registry_seed import seed_people


def _person(person_id: str, name: str) -> dict:
    return {
        "ids": [person_id],
        "name": name,
        "inferred": {"tier": "recurring", "evidence": {"count": 10}, "links": []},
        "confirmed": {"role": None, "links": [], "notes": None},
    }


def _family(*, owner: str | None = None) -> Store:
    """Gran, her children Bob and Alex, Bob's child Riley and Alex's child Sky."""
    people = [
        _person("id-gran", "Gran Example"),
        _person("id-bob", "Bob Example"),
        _person("id-alex", "Alex Example"),
        _person("id-riley", "Riley Example"),
        _person("id-sky", "Sky Example"),
    ]
    document: dict = {"version": 1, "people": people}
    if owner:
        document["owner"] = {"person_id": owner}
    store = seed_people(document)
    add_relationship(store, "id-gran", "parent-of", "id-bob")
    add_relationship(store, "id-gran", "parent-of", "id-alex")
    add_relationship(store, "id-bob", "parent-of", "id-riley")
    add_relationship(store, "id-alex", "parent-of", "id-sky")
    return store


def _suggested(store: Store, person_id: str) -> dict[tuple[str, str], str]:
    person = next(p for p in load_people(store) if p.person_id == person_id)
    return {
        (link.kind, link.target_id): link.via for link in person.links if link.status == SUGGESTED
    }


def _confirmed_links(store: Store, person_id: str) -> list[dict]:
    entry = next(e for e in people_entries(load_document(store)) if e["ids"][0] == person_id)
    return entry["confirmed"]["links"]


class TestTheRosterOffersWhatTheTreeImplies:
    def test_a_cousin_is_offered_with_the_chain_it_follows(self):
        store = _family()

        assert _suggested(store, "id-riley")[("cousin-of", "id-sky")] == (
            "child of Bob Example, who is a sibling of Alex Example, who is a parent of Sky Example"
        )

    def test_a_new_parent_link_brings_its_suggestions_at_once_without_a_scan(self):
        store = _family()
        remove_relationship(store, "id-bob", "parent-of", "id-riley")
        assert ("grandparent-of", "id-riley") not in _suggested(store, "id-gran")

        add_relationship(store, "id-riley", "child-of", "id-bob")

        assert _suggested(store, "id-gran")[("grandparent-of", "id-riley")] == (
            "parent of Bob Example, who is a parent of Riley Example"
        )

    def test_removing_the_fact_withdraws_an_unanswered_suggestion(self):
        store = _family()

        remove_relationship(store, "id-bob", "parent-of", "id-riley")

        assert ("grandparent-of", "id-riley") not in _suggested(store, "id-gran")

    def test_a_suggestion_is_never_written_to_the_registry(self):
        store = _family()

        load_people(store)

        assert all(link["kind"] != "cousin-of" for link in _confirmed_links(store, "id-riley"))


class TestAnsweringASuggestion:
    def test_accepting_one_records_it_and_its_reciprocal(self):
        store = _family()

        add_relationship(store, "id-riley", "cousin-of", "id-sky")

        assert ("cousin-of", "id-sky") not in _suggested(store, "id-riley")
        assert ("cousin-of", "id-riley") not in _suggested(store, "id-sky")
        assert any(link["kind"] == "cousin-of" for link in _confirmed_links(store, "id-sky"))

    def test_a_rejected_one_is_remembered_and_not_offered_again_from_either_side(self):
        store = _family()

        answer_person(
            store,
            "id-riley",
            role=None,
            notes=None,
            decisions={("cousin-of", "id-sky"): "rejected"},
        )

        assert ("cousin-of", "id-sky") not in _suggested(store, "id-riley")
        assert ("cousin-of", "id-riley") not in _suggested(store, "id-sky")
        riley = next(p for p in load_people(store) if p.person_id == "id-riley")
        rejected = [link for link in riley.links if link.kind == "cousin-of"]
        assert [link.status for link in rejected] == ["rejected"]

    def test_taking_a_rejection_back_offers_it_again(self):
        store = _family()
        decide = {("cousin-of", "id-sky"): "rejected"}
        answer_person(store, "id-riley", role=None, notes=None, decisions=decide)

        answer_person(
            store, "id-riley", role=None, notes=None, decisions={("cousin-of", "id-sky"): None}
        )

        assert ("cousin-of", "id-sky") in _suggested(store, "id-riley")

    def test_accept_all_records_every_suggestion_of_one_person(self):
        store = _family()
        offered = set(_suggested(store, "id-riley"))

        person = accept_suggestions(store, "id-riley")

        assert person is not None
        recorded = {(link["kind"], link["with"]) for link in _confirmed_links(store, "id-riley")}
        assert offered <= recorded
        assert not _suggested(store, "id-riley")

    def test_accept_all_leaves_other_peoples_suggestions_alone(self):
        store = _family()

        accept_suggestions(store, "id-riley")

        assert ("aunt-or-uncle-of", "id-sky") in _suggested(store, "id-bob")

    def test_accept_all_for_somebody_unknown_is_none(self):
        assert accept_suggestions(_family(), "id-nobody") is None


class TestAnAcceptedSuggestionReachesTheFilms:
    def test_an_accepted_cousin_of_the_owner_reads_as_their_cousin(self):
        store = _family(owner="id-riley")

        add_relationship(store, "id-sky", "cousin-of", "id-riley")

        people = read_library(store, EditorialConfig()).people
        assert people["id-sky"].role == "cousin"

    def test_a_suggestion_alone_gives_the_films_nothing(self):
        store = _family(owner="id-riley")

        people = read_library(store, EditorialConfig()).people
        assert people["id-sky"].role is None
