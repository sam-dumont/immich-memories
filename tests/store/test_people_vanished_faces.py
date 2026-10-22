"""An entry keeps its person when Immich retires the face id it names.

Immich can retire a face id: two records of one person merged (one shared in from a
household account), re-clustered, deleted. The entry, and every answer on it, must follow
the person to their new face instead of naming nothing while a rescan writes them again.
Every person and face here is invented.
"""

from __future__ import annotations

import copy
from datetime import datetime

from immich_memories.api.person_expression import PersonExpression
from immich_memories.people.account_ids import entry_ids
from immich_memories.people.companion import (
    edit_registry,
    load_document,
    people_entries,
    save_graph,
)
from immich_memories.people.graph import PeopleGraph, PersonNode
from immich_memories.people.signatures import PersonEvidence, Tier
from immich_memories.people.transfer import import_document
from immich_memories.people.vanished_faces import NEEDS_RELINK, heal_vanished_faces


def _person(ids, name, *, role=None, links=(), inferred_links=()):
    return {
        "ids": ids,
        "name": name,
        "birth_date": None,
        "inferred": {
            "tier": "inner",
            "counts_reliable": True,
            "evidence": {},
            "links": list(inferred_links),
        },
        "confirmed": {"role": role, "links": list(links), "notes": None},
    }


def _link(kind, target, reverse):
    return {"kind": kind, "with": target, "reverse": reverse, "decision": "confirmed"}


# Alex's answers sit on a face Immich retired; a rescan wrote Alex again under the face
# Immich has now, and Kit's reading and a saved group point at that new entry.
SPLIT = {
    "version": 1,
    "owner": {"person_id": "alex-gone", "name": "Alex Example", "identified": "confirmed"},
    "people": [
        _person(
            ["alex-gone"],
            "Alex Example",
            role="partner",
            links=[_link("parent-of", "kit", "child-of")],
        ),
        _person(
            ["kit"],
            "Kit Example",
            links=[_link("child-of", "alex-gone", "parent-of")],
            inferred_links=[{"kind": "close", "with": "alex-live", "confidence": 0.9, "via": "x"}],
        ),
        _person(["alex-live"], "alex example"),
    ],
    "groups": [
        {"label": "us", "expression": {"any": [{"person": "alex-live"}, {"person": "kit"}]}}
    ],
}
ROSTER = {"alex-live": "Alex Example", "kit": "Kit Example"}


def _heal(store, roster=ROSTER):
    return edit_registry(store, lambda document: heal_vanished_faces(document, roster))


def _scan_of(*person_ids: str) -> PeopleGraph:
    nodes = tuple(
        PersonNode(
            evidence=PersonEvidence(
                person_id=pid, name=f"Person {pid}", count=40, active_months=()
            ),
            tier=Tier.EVENT,
        )
        for pid in person_ids
    )
    return PeopleGraph(people=nodes, owner=None, built_at=datetime(2026, 9, 1, 8, 0, 0))


def test_the_rescans_second_entry_folds_into_the_one_with_the_answers(store):
    import_document(store, copy.deepcopy(SPLIT))

    assert _heal(store).folded == ["Alex Example"]

    document = load_document(store)
    alex, kit = people_entries(document)
    assert entry_ids(alex) == ["alex-gone", "alex-live"]
    assert alex["confirmed"]["role"] == "partner"
    assert alex["confirmed"]["links"] == [_link("parent-of", "kit", "child-of")]
    assert kit["confirmed"]["links"] == [_link("child-of", "alex-gone", "parent-of")]
    assert kit["inferred"]["links"][0]["with"] == "alex-gone"
    assert document["owner"]["person_id"] == "alex-gone"
    group = PersonExpression.from_dict(document["groups"][0]["expression"])
    assert group.leaf_values == ("alex-gone", "kit")


def test_a_rescan_keeps_the_person_whole_afterwards(store):
    import_document(store, copy.deepcopy(SPLIT))
    _heal(store)

    save_graph(store, _scan_of("alex-live", "kit"))
    _heal(store)

    assert [entry_ids(e) for e in people_entries(load_document(store))] == [
        ["alex-gone", "alex-live"],
        ["kit"],
    ]


def test_with_no_second_entry_the_one_face_carrying_the_name_is_bound(store):
    import_document(
        store, {"version": 1, "people": [_person(["alex-gone"], "Alex Example", role="partner")]}
    )

    assert _heal(store, {"alex-new": "Alex Example"}).relinked == ["Alex Example"]

    (alex,) = people_entries(load_document(store))
    assert entry_ids(alex) == ["alex-gone", "alex-new"]
    assert alex["confirmed"]["role"] == "partner"


def test_an_ambiguous_name_is_left_for_the_people_page_until_it_is_fixed(store):
    import_document(store, {"version": 1, "people": [_person(["alex-gone"], "Alex Example")]})

    assert _heal(store, {"a": "Alex Example", "b": "Alex Example"}).unresolved == ["Alex Example"]
    assert people_entries(load_document(store))[0][NEEDS_RELINK] is True

    _heal(store, {"a": "Alex Example"})
    assert NEEDS_RELINK not in people_entries(load_document(store))[0]


def test_two_live_entries_of_one_name_stay_two_people(store):
    # A parent and a child can share a name: names never merge two live faces.
    document = {
        "version": 1,
        "people": [_person(["sam-1"], "Sam Example"), _person(["sam-2"], "Sam Example")],
    }
    import_document(store, copy.deepcopy(document))

    healed = _heal(store, {"sam-1": "Sam Example", "sam-2": "Sam Example"})

    assert (healed.folded, healed.relinked, healed.unresolved) == ([], [], [])
    assert len(people_entries(load_document(store))) == 2


def test_a_face_another_entry_holds_is_never_taken(store):
    document = {
        "version": 1,
        "people": [_person(["alex-gone"], "Alex Example"), _person(["jo"], "Jo Example")],
    }
    import_document(store, copy.deepcopy(document))

    assert _heal(store, {"jo": "Alex Example"}).unresolved == ["Alex Example"]
