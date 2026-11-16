"""A delivered film's label is written to Immich again from the run page (#2627)."""

from __future__ import annotations

from contextlib import nullcontext

import httpx

from immich_memories.api.album_service import upload_waits
from immich_memories.api.film_relabel import RelabelOutcome, RelabelStatus
from immich_memories.web.run_upload import immich_opener
from tests.immich_fakes import fake_immich_client
from tests.web_api_fixtures import api_client, config_in, save_run

RUN = "20261007_120000_aaaa"


def _setup(tmp_path, outcome: RelabelOutcome | Exception, **run_fields):
    config = config_in(tmp_path)
    save_run(
        config, RUN, cut=False, status="completed", output_size_bytes=3_000_000_000, **run_fields
    )
    client = api_client(config)
    fake = fake_immich_client()
    if isinstance(outcome, Exception):
        fake.relabel_film.side_effect = outcome
    else:
        fake.relabel_film.return_value = outcome
    # WHY: Immich is the external boundary; the label write is the WRITE.
    client.app.dependency_overrides[immich_opener] = lambda: lambda: nullcontext(fake)
    return client, fake


def test_a_delivered_run_is_relabelled_and_the_answer_says_what_was_removed(tmp_path):
    client, fake = _setup(
        tmp_path,
        RelabelOutcome(RelabelStatus.WRITTEN, removed=("immich-memories/year/2024",)),
        immich_asset_id="asset-42",
    )

    response = client.post(f"/api/v1/runs/{RUN}/label")

    assert response.status_code == 200
    assert response.json() == {
        "status": "written",
        "detail": "",
        "removed_tags": ["immich-memories/year/2024"],
        "warnings": [],
    }
    (call,) = fake.relabel_film.call_args_list
    assert call.args[0] == "asset-42"
    assert call.kwargs["waits"] == upload_waits(3_000_000_000)


def test_a_label_that_already_matches_is_reported_unchanged(tmp_path):
    client, _ = _setup(
        tmp_path, RelabelOutcome(RelabelStatus.UNCHANGED), immich_asset_id="asset-42"
    )

    response = client.post(f"/api/v1/runs/{RUN}/label")

    assert (response.status_code, response.json()["status"]) == (200, "unchanged")


def test_a_film_gone_from_immich_is_a_clear_refusal(tmp_path):
    client, _ = _setup(
        tmp_path, RelabelOutcome(RelabelStatus.ASSET_GONE), immich_asset_id="asset-42"
    )

    response = client.post(f"/api/v1/runs/{RUN}/label")

    assert response.status_code == 409
    assert "no longer in Immich" in response.json()["detail"]


def test_a_key_without_the_rights_is_refused_naming_them(tmp_path):
    client, _ = _setup(
        tmp_path,
        RelabelOutcome(RelabelStatus.RIGHTS_MISSING, "the key lacks tag.asset"),
        immich_asset_id="asset-42",
    )

    response = client.post(f"/api/v1/runs/{RUN}/label")

    assert response.status_code == 409
    assert "tag.asset" in response.json()["detail"]


def test_a_run_never_delivered_is_refused_and_nothing_is_sent(tmp_path):
    client, fake = _setup(tmp_path, RelabelOutcome(RelabelStatus.WRITTEN))

    response = client.post(f"/api/v1/runs/{RUN}/label")

    assert response.status_code == 409
    assert "never delivered" in response.json()["detail"]
    fake.relabel_film.assert_not_called()


def test_an_unknown_run_is_not_found(tmp_path):
    client, _ = _setup(tmp_path, RelabelOutcome(RelabelStatus.WRITTEN))

    assert client.post("/api/v1/runs/nope/label").status_code == 404


def test_an_immich_failure_never_puts_the_server_address_in_the_answer(tmp_path):
    client, _ = _setup(
        tmp_path,
        httpx.ConnectError("cannot reach http://immich.internal.example:2283/api"),
        immich_asset_id="asset-42",
    )

    response = client.post(f"/api/v1/runs/{RUN}/label")

    assert response.status_code == 502
    assert "immich.internal.example" not in response.text
