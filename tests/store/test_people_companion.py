"""The people registry: what the graph writes down and what it must never touch.

Every person here is invented. A real registry holds a family's names, which is
why no fixture in this repo resembles one.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from immich_memories.db import Store
from immich_memories.people.companion import (
    add_confirmed_person,
    load_document,
    people_entries,
    save_confirmed,
    save_confirmed_relationship,
    save_graph,
)
from immich_memories.people.graph import Owner, PeopleGraph, PersonNode
from immich_memories.people.signatures import Link, LinkKind, PersonEvidence, Tier
from immich_memories.people.transfer import PeopleImportError, export_yaml, import_document


def _node(name: str, tier: Tier, count: int = 400, person_id: str | None = None) -> PersonNode:
    return PersonNode(
        evidence=PersonEvidence(
            person_id=person_id or f"id-{name.lower().replace(' ', '-')}",
            name=name,
            count=count,
            active_months=(date(2019, 1, 1), date(2019, 2, 1), date(2019, 3, 1)),
            birth_date=date(1990, 5, 6),
        ),
        tier=tier,
    )


def _graph(*nodes: PersonNode) -> PeopleGraph:
    return PeopleGraph(
        people=nodes,
        owner=Owner("id-alex-example", "Alex Example", "account"),
        built_at=datetime(2026, 8, 25, 9, 0, 0),
    )


class TestTheRegistry:
    def test_an_empty_store_reads_as_no_registry_at_all(self, store):
        assert load_document(store) == {}

    def test_a_fresh_scan_reserves_the_confirmed_fields_it_will_not_fill(self, store):
        save_graph(store, _graph(_node("Alex Example", Tier.INNER)))

        entry = people_entries(load_document(store))[0]
        assert entry["confirmed"] == {"role": None, "links": [], "notes": None}
        assert entry["inferred"]["tier"] == "inner"

    def test_the_registry_records_the_evidence_behind_each_reading(self, store):
        save_graph(store, _graph(_node("Alex Example", Tier.RECURRING, count=402)))

        evidence = people_entries(load_document(store))[0]["inferred"]["evidence"]
        assert evidence["count"] == 402
        assert evidence["active_months"] == 3

    def test_a_write_that_changes_nothing_leaves_the_registry_as_it_was(self, store):
        save_graph(store, _graph(_node("Alex Example", Tier.INNER)))
        before = export_yaml(store)

        add_confirmed_person(store, "Alex Example")

        assert export_yaml(store) == before


class TestConfirmedBeatsInferred:
    def test_a_confirmed_role_survives_a_refresh_that_disagrees(self, store):
        save_graph(store, _graph(_node("Alex Example", Tier.EPISODIC)))
        _confirm(store, "id-alex-example", role="partner")

        save_graph(store, _graph(_node("Alex Example", Tier.EVENT)))

        entry = people_entries(load_document(store))[0]
        assert entry["confirmed"]["role"] == "partner"
        assert entry["inferred"]["tier"] == "event"

    def test_confirmed_links_survive_a_refresh_that_inferred_others(self, store):
        save_graph(store, _graph(_node("Alex Example", Tier.INNER)))
        _confirm(store, "id-alex-example", links=[{"kind": "couple", "with": "id-sam-sample"}])

        refreshed = _node("Alex Example", Tier.INNER)
        refreshed = PersonNode(
            evidence=refreshed.evidence,
            tier=refreshed.tier,
            links=(Link(LinkKind.TIGHT_DYAD, refreshed.evidence.person_id, "id-kai", 0.4, "co"),),
        )
        save_graph(store, _graph(refreshed))

        entry = people_entries(load_document(store))[0]
        assert entry["confirmed"]["links"] == [{"kind": "couple", "with": "id-sam-sample"}]
        assert entry["inferred"]["links"][0]["with"] == "id-kai"

    def test_a_person_the_user_annotated_is_never_dropped_by_a_refresh(self, store):
        save_graph(
            store, _graph(_node("Alex Example", Tier.INNER), _node("Sam Sample", Tier.EVENT))
        )
        _confirm(store, "id-sam-sample", role="friend")

        save_graph(store, _graph(_node("Alex Example", Tier.INNER)))

        by_name = {entry["name"]: entry for entry in people_entries(load_document(store))}
        assert by_name["Sam Sample"]["confirmed"]["role"] == "friend"

    def test_one_relationship_answer_writes_both_directions(self, store):
        save_graph(
            store,
            _graph(_node("Alex Example", Tier.INNER), _node("Sam Sample", Tier.INNER)),
        )

        save_confirmed_relationship(store, "id-alex-example", "parent-of", "id-sam-sample")

        by_name = {entry["name"]: entry for entry in people_entries(load_document(store))}
        assert by_name["Alex Example"]["confirmed"]["links"] == [
            {
                "kind": "parent-of",
                "with": "id-sam-sample",
                "reverse": "child-of",
                "decision": "confirmed",
            }
        ]
        assert by_name["Sam Sample"]["confirmed"]["links"] == [
            {
                "kind": "child-of",
                "with": "id-alex-example",
                "reverse": "parent-of",
                "decision": "confirmed",
            }
        ]

    def test_an_off_camera_person_survives_a_refresh(self, store):
        save_graph(store, _graph(_node("Alex Example", Tier.INNER)))
        local_id = add_confirmed_person(store, "Robin Placeholder", role="family")

        save_graph(store, _graph(_node("Alex Example", Tier.INNER)))

        by_name = {entry["name"]: entry for entry in people_entries(load_document(store))}
        assert local_id.startswith("manual:")
        assert by_name["Robin Placeholder"]["confirmed"]["role"] == "family"

    def test_a_person_nobody_annotated_leaves_with_the_roster(self, store):
        save_graph(
            store, _graph(_node("Alex Example", Tier.INNER), _node("Sam Sample", Tier.EVENT))
        )

        save_graph(store, _graph(_node("Alex Example", Tier.INNER)))

        assert [entry["name"] for entry in people_entries(load_document(store))] == ["Alex Example"]


class TestTheEditorsWritePath:
    def test_it_fills_one_person_and_leaves_the_rest_of_the_registry_alone(self, store):
        save_graph(
            store, _graph(_node("Alex Example", Tier.INNER), _node("Sam Sample", Tier.EVENT))
        )

        save_confirmed(store, "id-sam-sample", {"role": "friend", "links": [], "notes": None})

        by_name = {entry["name"]: entry for entry in people_entries(load_document(store))}
        assert by_name["Sam Sample"]["confirmed"]["role"] == "friend"
        assert by_name["Alex Example"]["confirmed"]["role"] is None
        assert by_name["Alex Example"]["inferred"]["tier"] == "inner"

    def test_confirming_somebody_the_registry_does_not_hold_writes_nothing(self, store):
        save_graph(store, _graph(_node("Alex Example", Tier.INNER)))

        save_confirmed(store, "id-nobody", {"role": "friend", "links": [], "notes": None})

        assert [entry["ids"] for entry in people_entries(load_document(store))] == [
            ["id-alex-example"]
        ]


class TestAHandEditedImport:
    def test_an_id_written_without_brackets_is_refused_not_read_as_letters(self, store):
        # An export exists to be edited by hand, and `ids: 5f2c` without the
        # brackets is a string that iterates as characters everywhere after.
        with pytest.raises(PeopleImportError, match="ids"):
            import_document(store, {"version": 1, "people": [{"ids": "abc", "name": "Alex"}]})

        assert load_document(store) == {}

    def test_a_document_that_is_not_a_mapping_is_refused(self, store):
        with pytest.raises(PeopleImportError, match="mapping"):
            import_document(store, ["just", "a list"])


def _confirm(store: Store, person_id: str, **fields: object) -> None:
    """Stand in for the settings page that fills these in."""
    entry = next(e for e in people_entries(load_document(store)) if person_id in e["ids"])
    save_confirmed(store, person_id, {**entry["confirmed"], **fields})


class TestOneEntryPerPerson:
    def test_two_people_sharing_a_confirmed_block_do_not_become_yaml_anchors(self, store):
        # An entry that lists several ids — a person merged by hand, or the
        # cross-account identities to come — hands the same confirmed block to
        # two people. Written as one object, yaml emits `&id001`/`*id001`, and
        # an export meant to be hand-edited must not contain aliases: editing one
        # person silently edits the other, and deleting the anchor breaks both.
        import_document(
            store,
            {
                "version": 1,
                "people": [
                    {
                        "ids": ["id-alex-example", "id-sam-sample"],
                        "name": "Alex Example",
                        "confirmed": {"role": "partner", "links": []},
                    }
                ],
            },
        )

        save_graph(
            store, _graph(_node("Alex Example", Tier.INNER), _node("Sam Sample", Tier.INNER))
        )

        assert "&id" not in export_yaml(store)
        assert [entry["confirmed"]["role"] for entry in people_entries(load_document(store))] == [
            "partner",
            "partner",
        ]


class TestEraDayShares:
    def test_era_day_shares_reach_the_written_evidence(self, store):
        """The gathered share survives into the registry the confirm flow reads."""
        from dataclasses import replace

        node = _node("Alex Example", Tier.INNER)
        node = replace(node, evidence=replace(node.evidence, era_day_shares=(("covid", 0.3),)))
        save_graph(store, _graph(node))

        evidence = people_entries(load_document(store))[0]["inferred"]["evidence"]
        assert evidence["era_day_share"] == {"covid": 0.3}

    def test_an_unscanned_library_writes_no_era_block(self, store):
        save_graph(store, _graph(_node("Alex Example", Tier.INNER)))

        evidence = people_entries(load_document(store))[0]["inferred"]["evidence"]
        assert "era_day_share" not in evidence
