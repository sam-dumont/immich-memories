"""Owners and people across accounts, read and answered from the People page.

Every person, account and id here is invented.
"""

from __future__ import annotations

from dataclasses import dataclass

from immich_memories.config_models import ImmichConnection
from immich_memories.db import open_store
from immich_memories.people.transfer import import_document
from immich_memories.web.people_accounts import AccountPersonRecord, account_reads
from tests.web_api_fixtures import api_client, config_in


@dataclass
class _Reads:
    """# WHY: replaces Immich, the boundary an account's people and user name come from."""

    rosters: dict[str, list[AccountPersonRecord]]
    users: dict[str, str]

    def people(self, account: str) -> list[AccountPersonRecord]:
        return self.rosters[account]

    def user_name(self, account: str) -> str:
        return self.users[account]


def _entry(person_id, name, *, partner=None, birth_date=None, identified_tier="inner"):
    ids = {"primary": [person_id], "partner": [partner]} if partner else [person_id]
    return {
        "ids": ids,
        "name": name,
        "birth_date": birth_date,
        "inferred": {"tier": identified_tier, "counts_reliable": True, "evidence": {"count": 50}},
        "confirmed": {"role": None, "links": [], "notes": None},
    }


def _setup(tmp_path, entries, *, owner=None, reads=None):
    config = config_in(tmp_path)
    config.immich.accounts = {"partner": ImmichConnection(url="https://p.example", api_key="k")}
    document = {"version": 1, "people": entries}
    if owner:
        document["owner"] = owner
    import_document(open_store(config), document, replace=True)
    client = api_client(config)
    client.app.dependency_overrides[account_reads] = lambda: reads or _Reads({}, {})
    return client


def test_the_owner_of_each_account_is_listed_with_how_we_know_and_who_could_be_picked(tmp_path):
    client = _setup(
        tmp_path,
        [_entry("id-ana", "Ana Example", partner="p-ana"), _entry("id-luc", "Luc Sample")],
        owner={"person_id": "id-ana", "name": "Ana Example", "identified": "account"},
        reads=_Reads({}, {"partner": "Ana Example"}),
    )

    owners = {o["account"]: o for o in client.get("/api/v1/roster/owners").json()}

    assert owners["primary"]["name"] == "Ana Example" and owners["primary"]["how"] == "account"
    assert [c["name"] for c in owners["primary"]["choices"]] == ["Ana Example", "Luc Sample"]
    # The partner account's own user is asked for once, and its person is the one it names.
    assert owners["partner"]["name"] == "Ana Example" and owners["partner"]["how"] == "account"
    assert [c["name"] for c in owners["partner"]["choices"]] == ["Ana Example"]


def test_choosing_an_owner_is_kept_and_nobody_is_an_answer(tmp_path):
    client = _setup(
        tmp_path,
        [_entry("id-ana", "Ana Example"), _entry("id-luc", "Luc Sample")],
        owner={"person_id": "id-ana", "name": "Ana Example", "identified": "inferred"},
    )

    chosen = client.put("/api/v1/roster/owners/primary", json={"person_id": "id-luc"}).json()
    assert (chosen["name"], chosen["how"]) == ("Luc Sample", "confirmed")

    nobody = client.put("/api/v1/roster/owners/primary", json={"person_id": None}).json()
    assert nobody["nobody"] is True and nobody["name"] is None and nobody["how"] == "confirmed"
    assert client.get("/api/v1/roster/owners").json()[0]["nobody"] is True


def test_an_unknown_account_or_person_is_refused(tmp_path):
    client = _setup(tmp_path, [_entry("id-ana", "Ana Example")])

    assert client.put("/api/v1/roster/owners/ghost", json={"person_id": None}).status_code == 404
    assert (
        client.put("/api/v1/roster/owners/primary", json={"person_id": "id-nobody"}).status_code
        == 422
    )


def test_an_account_lists_its_named_people_suggesting_the_likely_match_first(tmp_path):
    reads = _Reads(
        {
            "partner": [
                AccountPersonRecord("p-zed", "Zed Other", None, 900),
                AccountPersonRecord("p-same-day", "Someone Else", "1990-05-06", 40),
                AccountPersonRecord("p-ana", "ana example", None, 10),
                AccountPersonRecord("p-bound", "Luc Sample", None, 5),
            ]
        },
        {},
    )
    client = _setup(
        tmp_path,
        [
            _entry("id-ana", "Ana Example", birth_date="1990-05-06"),
            _entry("id-luc", "Luc Sample", partner="p-bound"),
        ],
        reads=reads,
    )

    listed = client.get("/api/v1/accounts/partner/people", params={"for_person": "id-ana"}).json()

    assert [(p["id"], p["suggested"]) for p in listed] == [
        ("p-ana", True),
        ("p-same-day", True),
        ("p-zed", False),
        ("p-bound", False),
    ]
    assert listed[-1]["linked_to"] == "id-luc"
    assert listed[0]["pictures"] == 10


def test_a_person_declined_as_the_same_is_not_offered_again(tmp_path):
    reads = _Reads({"partner": [AccountPersonRecord("p-ana", "Ana Example", None, 10)]}, {})
    client = _setup(tmp_path, [_entry("id-ana", "Ana Example")], reads=reads)

    declined = client.post(
        "/api/v1/roster/id-ana/aliases/declined", json={"account": "partner", "alias_id": "p-ana"}
    )
    listed = client.get("/api/v1/accounts/partner/people", params={"for_person": "id-ana"}).json()

    assert declined.status_code == 200
    assert listed == []
    assert client.get("/api/v1/accounts/partner/people").json()[0]["id"] == "p-ana"
    assert client.get("/api/v1/accounts/ghost/people").status_code == 404


def test_linking_then_unlinking_puts_the_person_back_as_they_were(tmp_path):
    client = _setup(tmp_path, [_entry("id-ana", "Ana Example")])

    linked = client.post(
        "/api/v1/roster/id-ana/aliases", json={"account": "partner", "alias_id": "p-ana"}
    ).json()
    assert linked["aliases"]["partner"] == ["p-ana"]
    assert linked["alias_urls"]["p-ana"] == "https://p.example/people/p-ana"

    unlinked = client.request(
        "DELETE",
        "/api/v1/roster/id-ana/aliases",
        json={"account": "partner", "alias_id": "p-ana"},
    ).json()
    assert unlinked["aliases"] == {"primary": ["id-ana"]}
    assert (
        client.request(
            "DELETE",
            "/api/v1/roster/id-ana/aliases",
            json={"account": "partner", "alias_id": "p-ana"},
        ).status_code
        == 422
    )


def test_a_person_unlinked_is_offered_again_as_a_suggestion(tmp_path):
    reads = _Reads({"partner": [AccountPersonRecord("p-ana", "Ana Example", None, 10)]}, {})
    client = _setup(tmp_path, [_entry("id-ana", "Ana Example")], reads=reads)
    body = {"account": "partner", "alias_id": "p-ana"}
    client.post("/api/v1/roster/id-ana/aliases", json=body)
    client.request("DELETE", "/api/v1/roster/id-ana/aliases", json=body)

    listed = client.get("/api/v1/accounts/partner/people", params={"for_person": "id-ana"}).json()

    assert [(p["id"], p["suggested"]) for p in listed] == [("p-ana", True)]
