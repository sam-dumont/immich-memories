"""A person whose face changed in Immich is repaired wherever the app reads Immich's people.

No rescan: the People page, a film's start and native sharing each read the roster
already, and each saves the repair. Every person and face here is invented.
"""

from __future__ import annotations

import socket

import click
import pytest

from immich_memories.analysis.sources.person_resolution import PersonAlias, store_people
from immich_memories.api.access_clients import AccessBoundClient
from immich_memories.cli.run_people import resolve_run_people
from immich_memories.config.models.resources import ImmichConfig
from immich_memories.db import open_store
from immich_memories.people import companion
from immich_memories.people.account_ids import entry_ids
from immich_memories.people.companion import load_document, people_entries
from immich_memories.people.transfer import import_document
from immich_memories.people.vanished_faces import NEEDS_RELINK, heal_store
from immich_memories.web.roster import face_follower
from tests.household_fake import PRIMARY_KEY, FakeHousehold, immich_config
from tests.store.test_people_selection import HOUSEHOLD, _person
from tests.web_api_fixtures import api_client, config_in

GONE = {"version": 1, "people": [_person(["alex-gone"], "Alex"), _person(["kit"], "Kit")]}
ROSTER = {"alex-new": "Alex", "kit": "Kit"}


def _resolve(store, names, *, native_sharing=False, accounts=()):
    with AccessBoundClient(
        ImmichConfig(**immich_config(), native_sharing=native_sharing)
    ) as client:
        return resolve_run_people(
            client,
            expression=None,
            person_names=list(names),
            person_match="and",
            accounts=accounts,
            store=store,
        )


def _alex(store):
    return next(e for e in people_entries(load_document(store)) if e["name"] == "Alex")


def test_a_heal_saves_the_new_face_and_retires_the_old_one(store):
    import_document(store, GONE)

    assert heal_store(store, ROSTER).relinked == ["Alex"]

    alex = _alex(store)
    # The retired face stays the person's id, so every link naming it still holds.
    assert entry_ids(alex) == ["alex-gone", "alex-new"]
    assert alex["retired"] == ["alex-gone"]
    (person,) = (p for p in store_people(load_document(store)) if p.name == "Alex")
    assert person.person_id == "alex-gone"
    # Nothing asks Immich for the retired face again.
    assert person.aliases == (PersonAlias("alex-new", "primary"),)


def test_a_second_heal_writes_nothing(store, monkeypatch):
    import_document(store, GONE)
    heal_store(store, ROSTER)
    writes = []
    real_write = companion.write_document
    # WHY: count registry writes; the heal itself stays real.
    monkeypatch.setattr(
        companion, "write_document", lambda *a, **k: writes.append(1) or real_write(*a, **k)
    )

    heal_store(store, ROSTER)

    assert writes == []


def test_an_empty_roster_is_a_failed_read_and_changes_nothing(store):
    import_document(store, GONE)

    healed = heal_store(store, {})

    assert (healed.folded, healed.relinked, healed.unresolved) == ([], [], [])
    assert NEEDS_RELINK not in _alex(store)


def test_opening_the_people_page_saves_the_repair(tmp_path):
    config = config_in(tmp_path)
    import_document(open_store(config), GONE)
    client = api_client(config)
    client.app.dependency_overrides[face_follower] = lambda: lambda store: heal_store(store, ROSTER)

    people = {p["name"]: p for p in client.get("/api/v1/roster").json()["people"]}

    assert people["Alex"]["aliases"] == {"primary": ["alex-new"]}
    assert _alex(open_store(config))["retired"] == ["alex-gone"]


def test_the_people_page_opens_as_saved_when_immich_does_not_answer(tmp_path):
    config = config_in(tmp_path)
    import_document(open_store(config), GONE)
    client = api_client(config)
    client.app.dependency_overrides[face_follower] = lambda: lambda _store: None

    response = client.get("/api/v1/roster")

    assert response.status_code == 200
    assert "retired" not in _alex(open_store(config))


def test_an_unreachable_immich_reads_as_no_roster_at_once(tmp_path):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    config = config_in(tmp_path)
    config.immich.url = f"http://127.0.0.1:{port}"
    config.immich.api_key = "synthetic-key"  # noqa: S105 - a placeholder, never sent anywhere

    import_document(open_store(config), GONE)
    face_follower(config)(open_store(config))

    assert "retired" not in _alex(open_store(config))


def test_starting_a_film_saves_the_repair(store, monkeypatch):
    FakeHousehold(roster={PRIMARY_KEY: [{"id": "alex-new", "name": "Alex"}]}).install(monkeypatch)
    import_document(store, GONE)

    people = _resolve(store, ["Alex"])

    assert people.person_ids == ["alex-new"]
    assert _alex(store)["retired"] == ["alex-gone"]


def test_native_sharing_follows_a_face_immich_retired(store, monkeypatch):
    # Immich 3.3 answers 400 for an id it no longer has, not 404.
    FakeHousehold(
        roster={PRIMARY_KEY: [{"id": "alex-new", "name": "Alex"}]},
        version={"major": 3, "minor": 3, "patch": 5},
        clusters={PRIMARY_KEY: "cluster"},
        errors={"/api/people/alex-gone": 400},
    ).install(monkeypatch)
    import_document(store, GONE)

    people = _resolve(store, ["Alex"], native_sharing=True)

    assert people.person_ids == ["alex-new"]
    assert _alex(store)["retired"] == ["alex-gone"]


def test_a_name_with_no_single_face_still_stops_the_film(store, monkeypatch):
    FakeHousehold(
        roster={PRIMARY_KEY: [{"id": "a", "name": "Alex"}, {"id": "b", "name": "Alex"}]}
    ).install(monkeypatch)
    import_document(store, GONE)

    with pytest.raises(click.UsageError, match="exactly one person") as stopped:
        _resolve(store, ["Alex"])

    assert "rescan" not in str(stopped.value).lower()
    assert _alex(store)[NEEDS_RELINK] is True


def test_a_household_run_reads_the_partner_faces_unchanged(store, monkeypatch):
    FakeHousehold(roster={PRIMARY_KEY: [{"id": "kit", "name": "Kit"}]}).install(monkeypatch)
    import_document(store, {"version": 1, "people": [_person({"partner": ["kit-q"]}, "Kit")]})

    _resolve(store, ["Kit"], accounts=HOUSEHOLD)

    # Only primary faces are ever retired: the partner's own roster is not read here.
    assert "retired" not in people_entries(load_document(store))[0]


def _counts(**pictures):
    asked = []

    def count(face: str) -> int:
        asked.append(face)
        return pictures.get(face.replace("-", "_"), 0)

    return count, asked


def test_an_empty_face_with_a_namesake_that_has_pictures_is_followed(store):
    # Immich left Alex's old record behind with no pictures after a merge.
    import_document(store, GONE)
    count, _asked = _counts(alex_new=40, kit=12)

    healed = heal_store(store, {"alex-gone": "Alex", "alex-new": "Alex", "kit": "Kit"}, count)

    assert healed.relinked == ["Alex"]
    assert _alex(store)["retired"] == ["alex-gone"]


def test_an_empty_face_with_nothing_better_stays(store):
    import_document(store, GONE)
    count, _asked = _counts()

    healed = heal_store(store, {"alex-gone": "Alex", "alex-new": "Alex", "kit": "Kit"}, count)

    assert (healed.folded, healed.relinked) == ([], [])
    assert "retired" not in _alex(store)


def test_only_a_name_another_face_carries_is_counted(store):
    import_document(store, GONE)
    count, asked = _counts(alex_gone=3)

    heal_store(store, {"alex-gone": "Alex", "alex-new": "Alex", "kit": "Kit"}, count)

    # Kit's name is carried by one face only: no count read for Kit.
    assert "kit" not in asked
    assert "retired" not in _alex(store)


def test_people_this_library_never_had_stay_quiet_outside_a_scan(store):
    # An imported store, or a key for another user: nobody in Immich carries these names.
    import_document(store, GONE)

    heal_store(store, {"someone": "Someone Else"})

    assert all(NEEDS_RELINK not in entry for entry in people_entries(load_document(store)))


def test_a_scan_still_asks_about_a_name_nobody_carries(store):
    import_document(store, GONE)

    heal_store(store, {"someone": "Someone Else"}, scan=True)

    assert _alex(store)[NEEDS_RELINK] is True
