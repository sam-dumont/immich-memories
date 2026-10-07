"""Taking an account's id off a person, and remembering a "not the same person".

Every person and account here is invented.
"""

from __future__ import annotations

import copy

import pytest

from immich_memories.people.account_ids import ids_by_account
from immich_memories.people.companion import (
    decline_alias,
    declined_aliases,
    load_document,
    people_entries,
    save_graph,
    unbind_alias,
)
from immich_memories.people.graph import PeopleGraph
from immich_memories.people.transfer import export_yaml, import_document

LINKED = {
    "version": 1,
    "people": [
        {
            "ids": {"primary": ["id-alex"], "partner": ["partner-alex"]},
            "name": "Alex Example",
            "birth_date": None,
            "inferred": {"tier": "inner", "counts_reliable": True, "evidence": {}, "links": []},
            "confirmed": {"role": None, "links": [], "notes": None},
        },
    ],
}


def test_unlinking_takes_the_account_s_id_off_the_person_and_keeps_the_person(store):
    import_document(store, copy.deepcopy(LINKED))

    unbind_alias(store, "id-alex", "partner-alex", account="partner")

    (entry,) = people_entries(load_document(store))
    assert ids_by_account(entry) == {"primary": ["id-alex"]}
    assert entry["name"] == "Alex Example"


def test_the_primary_account_s_id_cannot_be_unlinked(store):
    import_document(store, copy.deepcopy(LINKED))

    with pytest.raises(ValueError, match="primary"):
        unbind_alias(store, "id-alex", "id-alex", account="primary")


def test_an_id_the_person_does_not_hold_in_that_account_is_refused(store):
    import_document(store, copy.deepcopy(LINKED))

    with pytest.raises(ValueError, match="partner-other"):
        unbind_alias(store, "id-alex", "partner-other", account="partner")


def test_a_not_the_same_person_answer_is_remembered_across_scans_and_exports(store):
    import_document(store, copy.deepcopy(LINKED))

    decline_alias(store, "id-alex", "partner", "partner-twin")
    decline_alias(store, "id-alex", "partner", "partner-twin")
    save_graph(store, PeopleGraph(people=()))

    assert declined_aliases(load_document(store)) == {"id-alex": {"partner": ["partner-twin"]}}
    exported = export_yaml(store)
    import_document(store, __import__("yaml").safe_load(exported), replace=True)
    assert declined_aliases(load_document(store)) == {"id-alex": {"partner": ["partner-twin"]}}
