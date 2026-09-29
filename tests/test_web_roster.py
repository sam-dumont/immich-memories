"""The people page answers the same registry `people scan` writes, through its own writer."""

from __future__ import annotations

from immich_memories.config_models import ImmichConnection
from tests.web_api_fixtures import api_client, config_in


def test_people_are_added_given_roles_and_related_through_the_registry_s_writer(tmp_path):
    client = api_client(config_in(tmp_path))

    ana = client.post("/api/v1/roster", json={"name": "Ana"}).json()
    luc = client.post("/api/v1/roster", json={"name": "Luc"}).json()
    client.put(
        f"/api/v1/roster/{ana['person_id']}", json={"role": "partner", "notes": "Loves hikes"}
    )
    related = client.post(
        f"/api/v1/roster/{ana['person_id']}/relationships",
        json={"kind": "partner-of", "target_id": luc["person_id"]},
    ).json()
    roster = client.get("/api/v1/roster").json()

    by_name = {person["name"]: person for person in roster["people"]}
    assert by_name["Ana"]["role"] == "partner" and by_name["Ana"]["notes"] == "Loves hikes"
    assert any(link["target_id"] == luc["person_id"] for link in related["links"])
    assert by_name["Luc"]["links"], "the registry keeps the reciprocal"
    assert {"kind": "partner-of", "label": "partner of"} in roster["relationships"]
    removed = client.request(
        "DELETE",
        f"/api/v1/roster/{ana['person_id']}/relationships",
        json={"kind": "partner-of", "target_id": luc["person_id"]},
    ).json()
    assert not any(link["target_id"] == luc["person_id"] for link in removed["links"])
    assert client.post("/api/v1/roster", json={"name": "  "}).status_code == 422


def test_binding_an_alias_adds_the_account_s_id_and_keeps_the_person_s_facts(tmp_path):
    client = api_client(config_in(tmp_path))
    ana = client.post("/api/v1/roster", json={"name": "Ana"}).json()

    bound = client.post(
        f"/api/v1/roster/{ana['person_id']}/aliases",
        json={"account": "partner", "alias_id": "partner-face-1"},
    ).json()

    assert bound["aliases"]["partner"] == ["partner-face-1"]
    assert bound["name"] == "Ana"
    # Binding the same id to the same account again is a no-op, not an error.
    again = client.post(
        f"/api/v1/roster/{ana['person_id']}/aliases",
        json={"account": "partner", "alias_id": "partner-face-1"},
    )
    assert again.status_code == 200
    assert again.json()["aliases"]["partner"] == ["partner-face-1"]


def test_binding_an_id_already_bound_elsewhere_is_refused(tmp_path):
    client = api_client(config_in(tmp_path))
    ana = client.post("/api/v1/roster", json={"name": "Ana"}).json()
    luc = client.post("/api/v1/roster", json={"name": "Luc"}).json()
    client.post(
        f"/api/v1/roster/{ana['person_id']}/aliases",
        json={"account": "partner", "alias_id": "shared-id"},
    )

    conflict = client.post(
        f"/api/v1/roster/{luc['person_id']}/aliases",
        json={"account": "partner", "alias_id": "shared-id"},
    )

    assert conflict.status_code == 422


def test_groups_round_trip_through_the_roster_api(tmp_path):
    client = api_client(config_in(tmp_path))
    ana = client.post("/api/v1/roster", json={"name": "Ana"}).json()

    saved = client.post(
        "/api/v1/roster/groups",
        json={"label": "kids", "expression": f'"{ana["person_id"]}"'},
    )
    assert saved.status_code == 201
    assert saved.json() == {"label": "kids", "expression": f'"{ana["person_id"]}"'}

    listed = client.get("/api/v1/roster/groups").json()
    assert listed == [{"label": "kids", "expression": f'"{ana["person_id"]}"'}]

    duplicate = client.post(
        "/api/v1/roster/groups", json={"label": "kids", "expression": f'"{ana["person_id"]}"'}
    )
    assert duplicate.status_code == 422

    malformed = client.post("/api/v1/roster/groups", json={"label": "broken", "expression": "("})
    assert malformed.status_code == 422
    assert {g["label"] for g in client.get("/api/v1/roster/groups").json()} == {"kids"}

    removed = client.delete("/api/v1/roster/groups/kids")
    assert removed.status_code == 204
    assert client.get("/api/v1/roster/groups").json() == []

    assert client.delete("/api/v1/roster/groups/kids").status_code == 404


def test_accounts_lists_primary_then_every_configured_extra_account(tmp_path):
    config = config_in(tmp_path)
    config.immich.accounts = {
        "partner": ImmichConnection(url="https://partner.example", api_key="k"),
    }
    client = api_client(config)

    listed = client.get("/api/v1/accounts").json()

    assert listed == [
        {"name": "primary", "primary": True},
        {"name": "partner", "primary": False},
    ]
