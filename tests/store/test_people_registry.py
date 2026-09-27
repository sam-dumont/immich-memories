"""The people registry lives in the store: what goes in comes back out, and nothing is lost.

Every person here is invented. A real registry holds a family's names and birth dates.
"""

from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

import pytest
import yaml

from immich_memories.people.companion import (
    load_document,
    people_entries,
    save_confirmed,
    save_graph,
)
from immich_memories.people.graph import PeopleGraph, PersonNode
from immich_memories.people.signatures import PersonEvidence, Tier
from immich_memories.people.transfer import (
    PeopleImportError,
    export_yaml,
    import_document,
    import_legacy,
    parse_yaml,
)

# The shape a scan writes, plus what a person adds by hand: aliases for a split face
# cluster, a manual person, a hand-typed link with no decision, an extra key on a person,
# a link somebody rejected, and one person the scan no longer sees.
LEGACY_DOCUMENT = {
    "version": 1,
    "generated": "2026-08-25T09:00:00",
    "owner": {"person_id": "id-alex", "name": "Alex Example", "identified": "account"},
    "people": [
        {
            "ids": ["id-alex", "id-alex-split"],
            "name": "Alex Example",
            "birth_date": "1990-05-06",
            "inferred": {
                "tier": "inner",
                "counts_reliable": True,
                "evidence": {
                    "count": 402,
                    "active_months": 31,
                    "first_month": "2016-01",
                    "last_month": "2026-08",
                    "span_years": 10.6,
                    "onset": None,
                    "concentration": 1.2,
                    "continuity": 0.84,
                    "era_day_share": {"before": 0.4, "after": 0.6},
                },
                "links": [
                    {"kind": "tight-dyad", "with": "id-sam", "confidence": 0.71, "via": "shared"}
                ],
            },
            "confirmed": {
                "role": None,
                "links": [
                    {
                        "kind": "partner-of",
                        "with": "id-sam",
                        "reverse": "partner-of",
                        "decision": "confirmed",
                    },
                    {"kind": "tight-dyad", "with": "id-robin", "decision": "rejected"},
                ],
                "notes": None,
            },
        },
        {
            "ids": ["id-sam"],
            "name": "Sam Sample",
            "birth_date": None,
            "inferred": {"tier": "inner", "counts_reliable": True, "evidence": {}, "links": []},
            "confirmed": {
                "role": "partner",
                "links": [{"kind": "partner-of", "with": "id-alex"}],
                "notes": "Met at the lake",
                "nickname": "S",
            },
            "pinned": True,
        },
        {
            "ids": ["manual:0b4f6a52-2a7e-4a55-9c1d-3f1a2b3c4d5e"],
            "name": "Robin Placeholder",
            "birth_date": None,
            "inferred": {"tier": None, "counts_reliable": False, "evidence": {}, "links": []},
            "confirmed": {"role": "grandparent", "links": [], "notes": None},
            "origin": "manual",
        },
        {
            "ids": ["id-kit"],
            "name": "Kit Example",
            "birth_date": "2019-03-01",
            "inferred": {"tier": "event", "counts_reliable": True, "evidence": {}, "links": []},
            "confirmed": {"role": None, "links": [], "notes": None},
        },
    ],
}


def test_a_document_comes_back_out_exactly_as_it_went_in(store):
    import_document(store, copy.deepcopy(LEGACY_DOCUMENT))

    assert yaml.safe_load(export_yaml(store)) == LEGACY_DOCUMENT


def _legacy_home(tmp_path, document=LEGACY_DOCUMENT):
    home = tmp_path / "home"
    home.mkdir()
    (home / "people.yaml").write_text(
        "# hand-edited\n" + yaml.dump(document, sort_keys=False, allow_unicode=True)
    )
    return home


def test_the_legacy_file_is_imported_whole_and_left_as_it_was(store, tmp_path):
    home = _legacy_home(tmp_path)
    legacy = home / "people.yaml"
    before = (legacy.read_bytes(), legacy.stat().st_mtime_ns)

    outcome = import_legacy(store, home)

    assert (outcome.imported, outcome.skipped, outcome.notes) == (4, 0, ())
    assert outcome.source == str(legacy)
    assert yaml.safe_load(export_yaml(store)) == LEGACY_DOCUMENT
    assert (legacy.read_bytes(), legacy.stat().st_mtime_ns) == before


def test_importing_the_legacy_file_twice_imports_nothing_the_second_time(store, tmp_path):
    home = _legacy_home(tmp_path)
    import_legacy(store, home)
    first = export_yaml(store)

    again = import_legacy(store, home)

    assert (again.imported, again.skipped) == (0, 4)
    assert export_yaml(store) == first


def test_a_legacy_answer_fills_a_person_the_store_knows_but_nobody_answered_for(store, tmp_path):
    save_graph(store, _scan_of("id-kit", "id-sam"))
    home = _legacy_home(tmp_path)

    outcome = import_legacy(store, home)

    by_id = {entry["ids"][0]: entry for entry in people_entries(load_document(store))}
    assert by_id["id-sam"]["confirmed"]["role"] == "partner"
    assert by_id["id-sam"]["inferred"]["tier"] == "event"
    assert "id-alex" in by_id and "manual:0b4f6a52-2a7e-4a55-9c1d-3f1a2b3c4d5e" in by_id
    assert (outcome.imported, outcome.skipped) == (3, 1)


def test_a_store_answer_is_never_replaced_by_the_legacy_file(store, tmp_path):
    save_graph(store, _scan_of("id-sam"))
    save_confirmed(store, "id-sam", {"role": "friend", "links": [], "notes": None})

    import_legacy(store, _legacy_home(tmp_path))

    by_id = {entry["ids"][0]: entry for entry in people_entries(load_document(store))}
    assert by_id["id-sam"]["confirmed"]["role"] == "friend"


def test_a_home_without_a_people_file_imports_nothing(store, tmp_path):
    outcome = import_legacy(store, tmp_path)

    assert (outcome.imported, outcome.skipped) == (0, 0)
    assert load_document(store) == {}


def test_a_malformed_legacy_person_is_skipped_with_a_reason_and_the_rest_imported(store, tmp_path):
    document = copy.deepcopy(LEGACY_DOCUMENT)
    document["people"].append({"ids": "id-no-brackets", "name": "Typo"})

    outcome = import_legacy(store, _legacy_home(tmp_path, document))

    assert (outcome.imported, outcome.skipped) == (4, 1)
    assert "people[4]" in outcome.notes[0]


def test_an_import_naming_one_id_twice_is_refused_and_writes_nothing(store):
    import_document(store, copy.deepcopy(LEGACY_DOCUMENT))
    before = export_yaml(store)
    document = copy.deepcopy(LEGACY_DOCUMENT)
    document["people"][1]["ids"].append("id-alex-split")

    with pytest.raises(PeopleImportError, match="twice"):
        import_document(store, document)

    assert export_yaml(store) == before


def test_an_import_replaces_the_registry_and_keeps_its_ids(store):
    save_graph(store, _scan_of("id-other"))

    count = import_document(store, copy.deepcopy(LEGACY_DOCUMENT), replace=True)

    ids = [entry["ids"] for entry in people_entries(load_document(store))]
    assert count == 4
    assert ids == [entry["ids"] for entry in LEGACY_DOCUMENT["people"]]


def test_an_import_over_a_registry_without_replace_changes_nothing(store):
    save_graph(store, _scan_of("id-other"))
    before = load_document(store)

    with pytest.raises(PeopleImportError, match="--replace"):
        import_document(store, copy.deepcopy(LEGACY_DOCUMENT))

    assert load_document(store) == before


def test_unquoted_yaml_dates_come_in_as_the_same_iso_text(store):
    text = "version: 1\npeople:\n  - ids: [id-kit]\n    name: Kit\n    birth_date: 2019-03-01\n"

    import_document(store, parse_yaml(text))

    assert people_entries(load_document(store))[0]["birth_date"] == "2019-03-01"


def test_two_writers_at_once_keep_every_confirmation(store):
    # A scan from the CLI and confirmations from the web UI land together; each is a
    # read-change-write of the whole registry, so without the registry lock one drops the other.
    people_ids = [f"id-{n}" for n in range(12)]
    save_graph(store, _scan_of(*people_ids))

    def confirm(person_id: str) -> None:
        save_confirmed(store, person_id, {"role": f"role-{person_id}", "links": [], "notes": None})

    with ThreadPoolExecutor(4) as pool:
        list(pool.map(confirm, people_ids))

    roles = {
        entry["ids"][0]: entry["confirmed"]["role"] for entry in load_document(store)["people"]
    }
    assert roles == {person_id: f"role-{person_id}" for person_id in people_ids}


def _scan_of(*person_ids: str) -> PeopleGraph:
    nodes = tuple(
        PersonNode(
            evidence=PersonEvidence(
                person_id=person_id,
                name=f"Person {person_id}",
                count=40,
                active_months=(date(2020, 1, 1),),
            ),
            tier=Tier.EVENT,
        )
        for person_id in person_ids
    )
    return PeopleGraph(people=nodes, owner=None, built_at=datetime(2026, 9, 1, 8, 0, 0))
