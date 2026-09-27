"""The people page answers the same file `people scan` writes, through its own writer."""

from __future__ import annotations

from immich_memories.web.roster import people_path
from tests.web_api_fixtures import api_client, config_in


def test_people_are_added_given_roles_and_related_through_the_file_s_writer(tmp_path):
    client = api_client(config_in(tmp_path))
    # WHY: the people file lives in $HOME; the test keeps it in its own directory.
    client.app.dependency_overrides[people_path] = lambda: tmp_path / "people.yaml"

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
    assert by_name["Luc"]["links"], "the file keeps the reciprocal"
    assert {"kind": "partner-of", "label": "partner of"} in roster["relationships"]
    removed = client.request(
        "DELETE",
        f"/api/v1/roster/{ana['person_id']}/relationships",
        json={"kind": "partner-of", "target_id": luc["person_id"]},
    ).json()
    assert not any(link["target_id"] == luc["person_id"] for link in removed["links"])
    assert client.post("/api/v1/roster", json={"name": "  "}).status_code == 422
