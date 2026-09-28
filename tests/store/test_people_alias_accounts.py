"""A person's aliases know which Immich account can read them.

The second account of a household gives the same person a different id. Binding that id
to the person is the owner's explicit answer: never a match by name, never a merge, and
never a reason to rewrite what the registry already says about the person.
Every person and account here is invented.
"""

from __future__ import annotations

import copy
from datetime import datetime

import pytest
import sqlalchemy as sa
import yaml

from immich_memories.db.tables import people_aliases
from immich_memories.people.companion import (
    bind_alias,
    load_document,
    people_entries,
    save_graph,
)
from immich_memories.people.graph import PeopleGraph, PersonNode
from immich_memories.people.signatures import PersonEvidence, Tier
from immich_memories.people.transfer import (
    PeopleImportError,
    export_yaml,
    import_document,
    parse_yaml,
)

TWO_ACCOUNTS = {
    "version": 1,
    "people": [
        {
            "ids": ["id-alex", "partner-alex", "partner-alex-split"],
            "accounts": {"partner-alex": "partner", "partner-alex-split": "partner"},
            "name": "Alex Example",
            "birth_date": "1990-05-06",
            "inferred": {"tier": "inner", "counts_reliable": True, "evidence": {}, "links": []},
            "confirmed": {"role": "partner", "links": [], "notes": None},
        },
        {
            "ids": ["id-kit"],
            "name": "Kit Example",
            "birth_date": None,
            "inferred": {"tier": "event", "counts_reliable": True, "evidence": {}, "links": []},
            "confirmed": {"role": None, "links": [], "notes": None},
        },
    ],
}


def test_an_alias_keeps_its_account_through_the_store_and_the_yaml(store):
    import_document(store, copy.deepcopy(TWO_ACCOUNTS))

    assert yaml.safe_load(export_yaml(store)) == TWO_ACCOUNTS


@pytest.mark.parametrize(
    ("accounts", "problem"),
    [
        ({"partner-robin": "partner"}, "`accounts` names an id this person does not have"),
        ({"partner-alex": ["partner"]}, "`accounts` must map each id to an account name"),
        (["partner"], "`accounts` must map each id to an account name"),
    ],
)
def test_an_import_refuses_an_account_it_cannot_place(store, accounts, problem):
    document = copy.deepcopy(TWO_ACCOUNTS)
    document["people"][0]["accounts"] = accounts

    with pytest.raises(PeopleImportError) as refused:
        import_document(store, document)

    assert refused.value.problems == (f"people[0]: {problem}",)
    assert load_document(store) == {}


def _one_account_registry(store):
    document = copy.deepcopy(TWO_ACCOUNTS)
    document["people"][0]["ids"] = ["id-alex"]
    del document["people"][0]["accounts"]
    import_document(store, copy.deepcopy(document))
    return document


def test_a_one_account_registry_exports_without_any_account(store):
    _one_account_registry(store)
    exported = export_yaml(store)

    import_document(store, parse_yaml(exported), replace=True)

    assert "accounts" not in exported
    assert export_yaml(store) == exported


class TestBindingAnAlias:
    def test_a_second_accounts_id_joins_the_person_and_changes_nothing_else(self, store):
        before = _one_account_registry(store)

        bind_alias(store, "id-alex", "partner-alex", account="partner")

        alex, kit = people_entries(load_document(store))
        assert alex["ids"] == ["id-alex", "partner-alex"]
        assert alex["accounts"] == {"partner-alex": "partner"}
        assert {key: alex[key] for key in ("name", "birth_date", "confirmed")} == {
            key: before["people"][0][key] for key in ("name", "birth_date", "confirmed")
        }
        assert kit == before["people"][1]

    def test_an_id_that_belongs_to_somebody_else_is_refused_not_merged(self, store):
        _one_account_registry(store)
        bind_alias(store, "id-kit", "partner-kit", account="partner")
        before = load_document(store)

        with pytest.raises(ValueError, match="already belongs to 'Kit Example'"):
            bind_alias(store, "id-alex", "partner-kit", account="partner")
        with pytest.raises(ValueError, match="already belongs"):
            bind_alias(store, "id-alex", "id-kit")

        assert load_document(store) == before

    def test_one_account_can_hold_several_ids_for_one_person(self, store):
        _one_account_registry(store)

        bind_alias(store, "id-alex", "partner-alex", account="partner")
        bind_alias(store, "partner-alex", "partner-alex-split", account="partner")

        assert yaml.safe_load(export_yaml(store))["people"][0] == TWO_ACCOUNTS["people"][0]

    def test_binding_again_is_a_no_op_and_another_account_is_refused(self, store):
        _one_account_registry(store)
        bind_alias(store, "id-alex", "partner-alex", account="partner")
        before = load_document(store)

        bind_alias(store, "id-alex", "partner-alex", account="partner")
        with pytest.raises(ValueError, match="another account"):
            bind_alias(store, "id-alex", "partner-alex", account="grandparent")

        assert load_document(store) == before

    def test_a_rescan_keeps_the_binding(self, store):
        _one_account_registry(store)
        bind_alias(store, "id-alex", "partner-alex", account="partner")
        bind_alias(store, "id-alex", "id-alex-split")

        save_graph(store, _scan_of("id-alex", "id-alex-split", "id-kit"))

        entries = people_entries(load_document(store))
        assert [entry["ids"] for entry in entries] == [
            ["id-alex", "partner-alex", "id-alex-split"],
            ["id-kit"],
        ]
        assert entries[0]["accounts"] == {"partner-alex": "partner"}

    def test_a_person_the_registry_does_not_hold_cannot_take_an_alias(self, store):
        _one_account_registry(store)

        with pytest.raises(ValueError, match="found 0"):
            bind_alias(store, "Alex Example", "partner-alex", account="partner")


def _scan_of(*person_ids: str) -> PeopleGraph:
    nodes = tuple(
        PersonNode(
            evidence=PersonEvidence(
                person_id=person_id, name=f"Person {person_id}", count=40, active_months=()
            ),
            tier=Tier.EVENT,
        )
        for person_id in person_ids
    )
    return PeopleGraph(people=nodes, owner=None, built_at=datetime(2026, 9, 1, 8, 0, 0))


def test_the_alias_rows_say_which_account_reads_each_id(store):
    import_document(store, copy.deepcopy(TWO_ACCOUNTS))

    with store.connect() as connection:
        rows = connection.execute(
            sa.select(people_aliases.c.alias_id, people_aliases.c.account)
        ).all()
    assert dict(rows) == {
        "id-alex": None,
        "partner-alex": "partner",
        "partner-alex-split": "partner",
        "id-kit": None,
    }
