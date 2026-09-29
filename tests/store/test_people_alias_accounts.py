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

from immich_memories.db.tables import people, people_aliases
from immich_memories.people.account_ids import entry_ids
from immich_memories.people.companion import (
    bind_alias,
    load_document,
    people_entries,
    save_confirmed_relationship,
    save_graph,
)
from immich_memories.people.graph import PeopleGraph, PersonNode
from immich_memories.people.signatures import PersonEvidence, Tier
from immich_memories.people.transfer import (
    EXPORT_HEADER,
    PeopleImportError,
    export_yaml,
    import_document,
    parse_yaml,
)

TWO_ACCOUNTS = {
    "version": 1,
    "people": [
        {
            "ids": {"primary": ["id-alex"], "partner": ["partner-alex", "partner-alex-split"]},
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


def test_an_export_import_export_round_trip_is_byte_identical(store):
    import_document(store, copy.deepcopy(TWO_ACCOUNTS))
    exported = export_yaml(store)

    import_document(store, parse_yaml(exported), replace=True)

    assert export_yaml(store) == exported


def test_accounts_are_written_primary_first_then_by_name(store):
    document = copy.deepcopy(TWO_ACCOUNTS)
    document["people"][0]["ids"] = {
        "partner": ["partner-alex"],
        "grandma_2": ["grandma-alex"],
        "primary": ["id-alex"],
    }

    import_document(store, document)

    written = yaml.safe_load(export_yaml(store))["people"][0]["ids"]
    assert list(written.items()) == [
        ("primary", ["id-alex"]),
        ("grandma_2", ["grandma-alex"]),
        ("partner", ["partner-alex"]),
    ]


def test_a_person_only_the_primary_account_reads_is_written_as_a_flat_list(store):
    document = copy.deepcopy(TWO_ACCOUNTS)
    document["people"][0]["ids"] = {"primary": ["id-alex"]}

    import_document(store, document)

    assert yaml.safe_load(export_yaml(store))["people"][0]["ids"] == ["id-alex"]


@pytest.mark.parametrize(
    ("ids", "problem"),
    [
        ({"Partner": ["partner-alex"]}, "account 'Partner' must be"),
        ({"part__ner": ["partner-alex"]}, "account 'part__ner' must be"),
        ({"partner": []}, "`ids.partner` must be a non-empty list of ids"),
        ({"partner": "partner-alex"}, "`ids.partner` must be a non-empty list of ids"),
        ({}, "`ids` must be a non-empty list of ids"),
        ({"primary": ["id-alex"], "partner": ["id-alex"]}, "an id is listed twice: id-alex"),
        ({"partner": ["id-kit"]}, "an id is listed twice: id-kit"),
    ],
)
def test_an_import_refuses_ids_it_cannot_place(store, ids, problem):
    document = copy.deepcopy(TWO_ACCOUNTS)
    document["people"] = [document["people"][1], document["people"][0]]
    document["people"][1]["ids"] = ids

    with pytest.raises(PeopleImportError) as refused:
        import_document(store, document)

    assert len(refused.value.problems) == 1
    assert refused.value.problems[0].startswith(f"people[1]: {problem}")
    assert load_document(store) == {}


def test_an_account_the_config_does_not_hold_yet_can_still_be_imported(store):
    document = copy.deepcopy(TWO_ACCOUNTS)
    document["people"][0]["ids"] = {"primary": ["id-alex"], "not_configured": ["other-alex"]}

    import_document(store, document)

    assert people_entries(load_document(store))[0]["ids"] == document["people"][0]["ids"]


def test_the_old_accounts_side_map_is_refused_with_the_new_shape_named(store):
    document = copy.deepcopy(TWO_ACCOUNTS)
    document["people"][0]["ids"] = ["id-alex", "partner-alex"]
    document["people"][0]["accounts"] = {"partner-alex": "partner"}

    with pytest.raises(PeopleImportError) as refused:
        import_document(store, document)

    (problem,) = refused.value.problems
    assert problem.startswith("people[0]: `accounts` is no longer read")
    assert "ids: {primary: [...], partner: [...]}" in problem
    assert load_document(store) == {}


def _one_account_registry(store):
    document = copy.deepcopy(TWO_ACCOUNTS)
    document["people"][0]["ids"] = ["id-alex"]
    import_document(store, copy.deepcopy(document))
    return document


ONE_ACCOUNT_EXPORT = """\
version: 1
people:
- ids:
  - id-alex
  name: Alex Example
  birth_date: '1990-05-06'
  inferred:
    tier: inner
    counts_reliable: true
    evidence: {}
    links: []
  confirmed:
    role: partner
    links: []
    notes: null
- ids:
  - id-kit
  name: Kit Example
  birth_date: null
  inferred:
    tier: event
    counts_reliable: true
    evidence: {}
    links: []
  confirmed:
    role: null
    links: []
    notes: null
"""


def test_a_one_account_registry_exports_exactly_as_it_always_did(store):
    _one_account_registry(store)
    exported = export_yaml(store)

    import_document(store, parse_yaml(exported), replace=True)

    assert exported == EXPORT_HEADER + ONE_ACCOUNT_EXPORT
    assert export_yaml(store) == exported


class TestBindingAnAlias:
    def test_a_second_accounts_id_joins_the_person_and_changes_nothing_else(self, store):
        before = _one_account_registry(store)

        bind_alias(store, "id-alex", "partner-alex", account="partner")

        alex, kit = people_entries(load_document(store))
        assert alex["ids"] == {"primary": ["id-alex"], "partner": ["partner-alex"]}
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
            {"primary": ["id-alex", "id-alex-split"], "partner": ["partner-alex"]},
            ["id-kit"],
        ]

    def test_primary_is_an_account_name_too(self, store):
        _one_account_registry(store)

        bind_alias(store, "id-alex", "id-alex-split", account="primary")

        assert people_entries(load_document(store))[0]["ids"] == ["id-alex", "id-alex-split"]

    def test_an_account_name_the_config_could_never_hold_is_refused(self, store):
        before = _one_account_registry(store)

        with pytest.raises(ValueError, match="account 'Partner' must be"):
            bind_alias(store, "id-alex", "partner-alex", account="Partner")

        assert people_entries(load_document(store)) == before["people"]

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


def _partner_only_robin(store):
    """Robin reached the registry through the partner account; Kit is linked to that id."""
    document = copy.deepcopy(TWO_ACCOUNTS)
    robin = copy.deepcopy(document["people"][1])
    robin |= {"ids": {"partner": ["partner-robin"]}, "name": "Robin Example"}
    document["people"].append(robin)
    import_document(store, document)
    save_confirmed_relationship(store, "id-kit", "partner-of", "partner-robin")


def _person_ids(store):
    with store.connect() as connection:
        return set(connection.execute(sa.select(people.c.person_id)).scalars())


class TestTheStoreIdIsIdentity:
    """#951: the canonical person reference never moves because ids were added or reordered."""

    def test_binding_a_primary_id_keeps_the_person_id_the_partner_account_gave(self, store):
        _partner_only_robin(store)

        bind_alias(store, "partner-robin", "id-robin")

        assert "partner-robin" in _person_ids(store)
        robin = people_entries(load_document(store))[2]
        assert robin["ids"] == {"primary": ["id-robin"], "partner": ["partner-robin"]}
        assert entry_ids(robin)[0] == "partner-robin"

    def test_the_export_says_which_id_is_the_person_and_round_trips_it(self, store):
        _partner_only_robin(store)
        bind_alias(store, "partner-robin", "id-robin")
        exported = export_yaml(store)

        import_document(store, parse_yaml(exported), replace=True)

        assert yaml.safe_load(exported)["people"][2]["person_id"] == "partner-robin"
        assert "partner-robin" in _person_ids(store)
        assert export_yaml(store) == exported

    def test_a_person_whose_first_listed_id_is_its_own_carries_no_person_id(self, store):
        import_document(store, copy.deepcopy(TWO_ACCOUNTS))

        assert "person_id" not in export_yaml(store)

    def test_relationship_links_still_name_the_person(self, store):
        _partner_only_robin(store)

        bind_alias(store, "partner-robin", "id-robin")

        kit = people_entries(load_document(store))[1]
        assert [link["with"] for link in kit["confirmed"]["links"]] == ["partner-robin"]

    def test_a_rescan_of_the_primary_account_keeps_the_identity(self, store):
        _partner_only_robin(store)
        bind_alias(store, "partner-robin", "id-robin")

        save_graph(store, _scan_of("id-alex", "id-robin", "id-kit"))

        entries = people_entries(load_document(store))
        assert [entry_ids(entry)[0] for entry in entries] == ["id-alex", "partner-robin", "id-kit"]
        assert "partner-robin" in _person_ids(store)

    def test_an_import_refuses_a_person_id_the_entry_does_not_hold(self, store):
        document = copy.deepcopy(TWO_ACCOUNTS)
        document["people"][0]["person_id"] = "id-kit"

        with pytest.raises(PeopleImportError) as refused:
            import_document(store, document)

        assert refused.value.problems == ("people[0]: `person_id` must be one of the person's ids",)


def test_a_rescan_keeps_a_person_only_a_second_account_reads(store):
    document = copy.deepcopy(TWO_ACCOUNTS)
    document["people"][1]["ids"] = {"partner": ["partner-kit"]}
    import_document(store, document)

    save_graph(store, _scan_of("id-alex"))

    assert [entry_ids(entry) for entry in people_entries(load_document(store))] == [
        ["id-alex", "partner-alex", "partner-alex-split"],
        ["partner-kit"],
    ]
