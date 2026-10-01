"""A remote household cut reads its sources through the same accounts as a local cut."""

import threading
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from test_app_handoff import manual_params
from test_live_contract import LiveAssets, live_body
from test_worker import _settle

from conftest import AUTH, render_request_body, worker_app


def household_params(tmp_path):
    from immich_memories.api.compatibility import ApiVersionPolicy
    from immich_memories.config_models import ImmichConnection

    params = manual_params(tmp_path)
    params.config.immich.api_version = ApiVersionPolicy.V2
    params.config.immich.accounts = {
        name: ImmichConnection(
            url=params.config.immich.url, api_key=f"synthetic-{name}-key", api_version="v2"
        )
        for name in ("partner", "unused")
    }
    params.clips[0].asset.access_accounts = ("partner", "primary")
    return params


@pytest.mark.parametrize("mixed", [False, True])
def test_partner_only_and_mixed_cuts_route_metadata_and_originals(tmp_path, monkeypatch, mixed):
    from immich_memories_render_worker.access import render_client
    from immich_memories_render_worker.admission import certify_envelope
    from immich_memories_render_worker.models import RenderRequest
    from immich_memories_render_worker.native_plan import generation_params

    from immich_memories.api.models import VideoClipInfo
    from immich_memories.processing.remote_render_plan import build_render_request

    params = household_params(tmp_path)
    if mixed:
        asset = params.clips[0].asset.model_copy(
            update={"id": str(uuid4()), "access_accounts": ("primary",)}
        )
        params.clips.append(VideoClipInfo(asset=asset, duration_seconds=10))
        params.clip_segments[asset.id] = (2.5, 5.75)
    owners = {c.asset.id: c.asset.access_accounts[0] for c in params.clips}
    keys = {"primary": params.config.immich.api_key, "partner": "synthetic-partner-key"}
    reads = []

    def handler(request):
        key = request.headers["x-api-key"]
        if request.url.path.endswith("/users/me"):
            return httpx.Response(200, json={"id": "partner-id", "email": "partner@example.test"})
        asset_id = request.url.path.split("/assets/")[1].split("/")[0]
        reads.append((asset_id, key))
        if key != keys[owners[asset_id]]:
            return httpx.Response(403, json={"message": "Not this account's asset"})
        if request.url.path.endswith("/original"):
            return httpx.Response(200, content=b"synthetic original")
        asset = next(c.asset for c in params.clips if c.asset.id == asset_id)
        return httpx.Response(200, json=asset.model_dump(mode="json", by_alias=True))

    real_client = httpx.AsyncClient
    # WHY: exercise the real account router and HTTP clients against a synthetic Immich server.
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    body = build_render_request(params)
    assert set(body["immich"]["accounts"]) == {"partner"}
    wire = httpx.Request("POST", "http://worker.invalid/jobs", json=body)
    request = RenderRequest.model_validate_json(wire.content)
    certify_envelope(request)
    with render_client(request) as client:
        restored = generation_params(request, tmp_path / "worker", client, lambda *_: None)
        # Downloads also use sibling clients in the app's prefetch threads.
        with client.sibling() as sibling:
            for clip in restored.clips:
                sibling.download_asset(clip.asset.id, tmp_path / f"{clip.asset.id}.mp4")
    assert {c.asset.id: c.asset.access_accounts[0] for c in restored.clips} == owners
    assert set(restored.config.immich.accounts) == {"partner"}
    assert reads == [(c.asset.id, keys[owners[c.asset.id]]) for c in params.clips] * 2
    assert "synthetic-partner-key" not in repr(request)


def test_live_sources_keep_pinned_routes_and_reach_worker_siblings(tmp_path):
    from immich_memories_render_worker.access import render_client
    from immich_memories_render_worker.models import RenderRequest
    from immich_memories_render_worker.native_plan import generation_params

    from immich_memories.api.access_clients import AccessBoundClient
    from immich_memories.processing.remote_render_plan import build_render_request

    body, material = live_body()
    params = generation_params(
        RenderRequest.model_validate(body), tmp_path, LiveAssets(material), lambda *_: None
    )
    params.config.immich = household_params(tmp_path).config.immich
    params.clips[0].asset.access_accounts = ("partner",)
    with AccessBoundClient(params.config.immich) as source_client:
        params.client = source_client
        source_client.routes.pin({material.video_ids[1]: "primary"})
        envelope = build_render_request(params)
    expected = dict.fromkeys([*material.still_ids, *material.video_ids], "partner")
    expected[material.video_ids[1]] = "primary"
    assert envelope["asset_accounts"] == expected
    with (
        render_client(RenderRequest.model_validate(envelope)) as client,
        client.sibling() as sibling,
    ):
        assert {asset_id: sibling.routes.account_of(asset_id) for asset_id in expected} == expected


@pytest.mark.parametrize("problem", ["missing", "different_server"])
def test_unusable_selected_account_is_refused_before_submission(tmp_path, problem):
    from immich_memories.processing.remote_render_plan import build_render_request

    params = household_params(tmp_path)
    if problem == "missing":
        params.config.immich.accounts.pop("partner")
    else:
        params.config.immich.accounts["partner"].url = "https://other.example.test"
    with pytest.raises(ValueError, match="not configured|configured Immich server"):
        build_render_request(params)


def test_old_single_account_envelopes_keep_the_plain_client():
    from immich_memories_render_worker.access import render_client
    from immich_memories_render_worker.models import RenderRequest

    from immich_memories.api.sync_client import SyncImmichClient

    with render_client(RenderRequest.model_validate(render_request_body())) as client:
        assert type(client) is SyncImmichClient


@pytest.mark.parametrize("problem", ["unknown_route", "invalid_name", "empty_key", "extra_url"])
def test_invalid_household_access_is_rejected_without_echoing_keys(tmp_path, problem):
    body = render_request_body()
    secret = uuid4().hex
    body["immich"]["accounts"] = {"partner": {"api_key": secret}}
    if problem == "unknown_route":
        body["asset_accounts"] = {body["plan"]["clips"][0]["asset_id"]: "missing"}
    elif problem == "invalid_name":
        body["immich"]["accounts"] = {"primary": {"api_key": secret}}
    elif problem == "empty_key":
        body["immich"]["accounts"]["partner"]["api_key"] = " "
    else:
        body["immich"]["accounts"]["partner"]["url"] = "https://other.example.test"

    class Renderer:
        def health(self):
            return {"ready": True}

    with TestClient(worker_app(tmp_path, Renderer()), headers=AUTH) as client:
        response = client.post("/jobs", json=body)
    assert response.status_code == 422
    assert secret not in response.text


def test_all_keys_are_redacted_and_partner_key_changes_conflict(tmp_path, caplog):
    release = threading.Event()
    body = render_request_body()
    body["immich"]["accounts"] = {"partner": {"api_key": "synthetic-partner-secret"}}
    body["asset_accounts"] = {body["plan"]["clips"][0]["asset_id"]: "partner"}
    secrets = (body["immich"]["api_key"], "synthetic-partner-secret")

    class Renderer:
        def health(self):
            return {"ready": True}

        def render(self, request, directory, progress):
            assert release.wait(5)
            message = " ".join(secrets)
            progress(message, 0.5, message)
            raise RuntimeError(message)

    with TestClient(worker_app(tmp_path, Renderer()), headers=AUTH) as client:
        try:
            response = client.post("/jobs", json=body)
            assert response.status_code == 202
            job_id = response.json()["job_id"]
            body["immich"]["accounts"]["partner"]["api_key"] = "synthetic-changed-key"
            assert client.post("/jobs", json=body).status_code == 409
        finally:
            release.set()
        status = _settle(client, job_id)
        assert status.json()["state"] == "failed"
        assert status.json()["message"] == "[redacted] [redacted]"
        assert status.json()["error"] == "[redacted] [redacted]"
        assert not any(secret in status.text for secret in secrets)
    records = list(tmp_path.rglob("*.json"))
    assert records
    assert not any(secret in row.read_text() for row in records for secret in secrets)
    assert not any(secret in caplog.text for secret in secrets)
