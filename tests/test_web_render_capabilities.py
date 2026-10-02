"""The render form receives exact missing scopes without exposing its key."""

import pytest

from immich_memories.web.render_capabilities import immich_render_capabilities
from tests.web_api_fixtures import api_client, config_in


@pytest.mark.parametrize("missing", [(), ("asset.upload",), ("tag.create", "tag.asset")])
def test_render_upload_availability_names_each_missing_scope(tmp_path, missing):
    client = api_client(config_in(tmp_path))
    client.app.dependency_overrides[immich_render_capabilities] = lambda: lambda: missing
    answer = client.get("/api/v1/render/capabilities")
    assert answer.status_code == 200
    body = answer.json()
    assert body["upload_available"] is (not missing)
    assert body["missing_upload"] == list(missing)
    assert all(permission in body["upload_reason"] for permission in missing)
    if not missing:
        assert body["upload_reason"] is None


def test_permission_probe_failure_disables_only_upload_and_never_exposes_secrets(tmp_path):
    import httpx

    def unavailable():
        raise httpx.ConnectError("provider-secret-key")

    client = api_client(config_in(tmp_path))
    client.app.dependency_overrides[immich_render_capabilities] = lambda: unavailable
    body = client.get("/api/v1/render/capabilities").json()
    assert body["upload_available"] is False
    assert "rendered and downloaded" in body["upload_reason"]
    assert "provider-secret-key" not in str(body)
