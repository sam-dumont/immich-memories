"""An rc.5 store, opened and scanned by this release.

`tests/fixtures/rc5_people_store.sql` is the dump of a SQLite store written by the published
1.0.0rc5 wheel itself (its own scan writer, its own People page answer, its own `groups` writer):
two people the scan linked as a tight dyad, one of them confirmed that link without ever saying
what the two are to each other, an owner the scan guessed, and one saved group.
Every person is invented.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

import pytest

from immich_memories.db import Store, StoreLocation, close_stores, open_store
from immich_memories.people.companion import (
    load_document,
    save_graph,
)
from immich_memories.people.context import load_people_prompt_context
from immich_memories.people.editor import add_relationship, load_people
from immich_memories.people.graph import Owner, PeopleGraph, PersonNode
from immich_memories.people.groups import list_groups
from immich_memories.people.owner import confirmed_owner
from immich_memories.people.signatures import Link, LinkKind, PersonEvidence, Tier

_DUMP = Path(__file__).resolve().parents[1] / "fixtures" / "rc5_people_store.sql"


@pytest.fixture
def rc5_store(tmp_path) -> Store:
    path = tmp_path / "store.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(_DUMP.read_text())
    store = open_store(location=StoreLocation(url=f"sqlite:///{path}"))
    yield store
    close_stores()


def _rescan(store: Store) -> None:
    def node(person_id: str, name: str, other: str) -> PersonNode:
        evidence = PersonEvidence(person_id, name, 410, (date(2019, 1, 1), date(2019, 2, 1)))
        link = Link(LinkKind.TIGHT_DYAD, person_id, other, 0.8, "co-occurrence")
        return PersonNode(evidence=evidence, tier=Tier.INNER, links=(link,))

    graph = PeopleGraph(
        people=(node("id-ana", "Ana Example", "id-luc"), node("id-luc", "Luc Sample", "id-ana")),
        owner=Owner("id-ana", "Ana Example", "inferred"),
        built_at=datetime(2026, 10, 8, 9, 0, 0),
    )
    save_graph(store, graph)


def test_a_scan_of_an_rc5_store_keeps_its_saved_group(rc5_store):
    _rescan(rc5_store)

    assert [saved.label for saved in list_groups(rc5_store)] == ["pair"]


def test_the_rc5_owner_is_still_a_guess_after_the_upgrade_and_a_scan(rc5_store):
    _rescan(rc5_store)

    document = load_document(rc5_store)
    assert document["owner"]["identified"] == "inferred"
    assert confirmed_owner(document) is None


def test_a_dyad_confirmed_in_rc5_reads_as_linked_but_not_named_and_is_not_a_relationship(
    rc5_store,
):
    _rescan(rc5_store)

    rows = {
        person.name: [(link.kind, link.status) for link in person.links]
        for person in load_people(rc5_store)
    }

    assert rows == {
        "Ana Example": [("tight-dyad", "unnamed")],
        "Luc Sample": [("tight-dyad", "unnamed")],
    }
    assert load_people_prompt_context(rc5_store)["id-ana"].relationships == ()


def test_naming_the_pair_replaces_the_placeholder(rc5_store):
    _rescan(rc5_store)

    add_relationship(rc5_store, "id-ana", "partner-of", "id-luc")

    rows = {p.name: [(link.kind, link.status) for link in p.links] for p in load_people(rc5_store)}
    assert rows == {
        "Ana Example": [("partner-of", "named")],
        "Luc Sample": [("partner-of", "named")],
    }
