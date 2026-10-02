"""API-key capability policy over the real HTTP client, without a library mutation."""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from immich_memories.api.immich import SyncImmichClient
from immich_memories.api.permissions import READ_PERMISSIONS


@contextmanager
def permission_server(permissions, *, assets=None):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            body = {
                "/api/server/version": {"major": 3, "minor": 2, "patch": 2},
                "/api/users/me": {"id": "operator", "email": "operator@example.invalid"},
                "/api/api-keys/me": {"permissions": permissions},
                **(assets or {}),
            }.get(self.path, {})
            if callable(body):
                body = body()
            status = (
                403
                if self.path == "/api/users/me"
                and not ("user.read" in permissions or "all" in permissions)
                else 200
            )
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def do_POST(self):
            requests.append(self.path)
            query = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            body = (assets or {}).get(self.path, {})
            if callable(body):
                body = body(query)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_key_missing_read_permissions_is_refused_with_exact_names():
    with (
        permission_server(["user.read"]) as (url, requests),
        SyncImmichClient(url, "synthetic-key") as client,
    ):
        from immich_memories.api.permissions import MissingReadPermissions

        with pytest.raises(
            MissingReadPermissions,
            match=r"API key lacks required read permissions: .*asset.download",
        ):
            client.require_read_permissions()
        assert requests == ["/api/api-keys/me"]


def test_preflight_names_missing_read_permissions_instead_of_reporting_connected():
    from immich_memories.config_loader import Config
    from immich_memories.preflight import CheckStatus
    from immich_memories.preflight_immich import check_immich

    with permission_server(["user.read"]) as (url, _requests):
        config = Config(tier="nas", immich={"url": url, "api_key": "synthetic-key"})
        result = check_immich(config)
    assert result.status is CheckStatus.ERROR
    assert "asset.download" in (result.details or "")


def test_preflight_names_missing_user_read_before_calling_the_denied_user_route():
    from immich_memories.config_loader import Config
    from immich_memories.preflight import CheckStatus
    from immich_memories.preflight_immich import check_immich

    with permission_server([]) as (url, requests):
        result = check_immich(Config(tier="nas", immich={"url": url, "api_key": "synthetic-key"}))
    assert result.status is CheckStatus.ERROR
    assert "user.read" in (result.details or "")
    assert "/api/users/me" not in requests


def test_cut_client_refuses_incomplete_read_scope_before_discovering_assets():
    from immich_memories.api.permissions import MissingReadPermissions
    from immich_memories.cli.run_people import run_client
    from immich_memories.config_loader import Config

    with permission_server(["user.read"]) as (url, requests):
        config = Config(tier="nas", immich={"url": url, "api_key": "synthetic-key"})
        with pytest.raises(MissingReadPermissions, match="asset.download"):
            run_client(config.immich, ())
        assert requests == ["/api/api-keys/me"]


def test_minimum_read_key_still_excludes_previously_generated_films():
    from immich_memories.api.permissions import READ_PERMISSIONS

    assets = {
        "/api/search/metadata": {
            "assets": {"items": [{"id": "film"}, {"id": "source"}], "nextPage": None}
        },
        "/api/assets/film": {"id": "film", "tags": [{"value": "immich-memories/generated"}]},
        "/api/assets/source": {"id": "source", "tags": [{"value": "holiday"}]},
    }
    with (
        permission_server(list(READ_PERMISSIONS), assets=assets) as (url, requests),
        SyncImmichClient(url, "synthetic-key") as client,
    ):
        assert client.generated_asset_ids() == frozenset({"film"})
        assert "/api/tags" not in requests


def test_capabilities_are_read_once_per_client_even_when_multiple_consumers_ask():
    from immich_memories.api.permissions import READ_PERMISSIONS

    with (
        permission_server(list(READ_PERMISSIONS)) as (url, requests),
        SyncImmichClient(url, "synthetic-key") as client,
    ):
        client.require_read_permissions()
        client.get_key_capabilities()
        client.require_read_permissions()
        assert requests == ["/api/api-keys/me"]


@pytest.mark.parametrize("permissions", [["all"], list(READ_PERMISSIONS)])
def test_config_test_warns_about_rights_without_refusing_a_readable_key(permissions, tmp_path):
    from click.testing import CliRunner

    from immich_memories.cli import main

    with permission_server(permissions) as (url, _requests):
        path = tmp_path / "config.yaml"
        path.write_text(f"tier: nas\nimmich:\n  url: {url}\n  api_key: synthetic-key\n")
        result = CliRunner().invoke(main, ["--config", str(path), "config", "test"])
    assert result.exit_code == 0, result.output
    expected = "whole library" if "all" in permissions else "asset.upload"
    assert expected in result.output


def test_partner_account_missing_read_scope_is_named_in_preflight():
    from immich_memories.config_loader import Config
    from immich_memories.preflight import CheckStatus
    from immich_memories.preflight_accounts import check_extra_accounts

    with permission_server(["user.read"]) as (url, _requests):
        config = Config(
            tier="nas", immich={"accounts": {"partner": {"url": url, "api_key": "synthetic-key"}}}
        )
        result = check_extra_accounts(config)[0]
    assert result.status is CheckStatus.ERROR
    assert result.name == "Immich account partner"
    assert "asset.download" in (result.details or "")


@pytest.mark.parametrize("permissions", [None, "all", ["all", 7]])
def test_malformed_permission_reply_cannot_grant_read_access(permissions):
    from immich_memories.api.immich import ImmichAPIError

    with (
        permission_server(permissions) as (url, _requests),
        SyncImmichClient(url, "synthetic-key") as client,
        pytest.raises(ImmichAPIError, match="Malformed API key permissions response"),
    ):
        client.require_read_permissions()


def test_generated_film_exclusion_pages_video_reads_with_inline_or_detail_tags():
    def page(query):
        assert query["type"] == "VIDEO"
        if int(query["page"]) == 1:
            return {
                "assets": {
                    "items": [{"id": "first", "tags": [{"value": "immich-memories/generated"}]}],
                    "nextPage": "2",
                }
            }
        return {"assets": {"items": [{"id": "second"}], "nextPage": None}}

    assets = {
        "/api/search/metadata": page,
        "/api/assets/second": {"tags": [{"value": "immich-memories/generated"}]},
    }
    with (
        permission_server(list(READ_PERMISSIONS), assets=assets) as (url, requests),
        SyncImmichClient(url, "synthetic-key") as client,
    ):
        assert client.generated_asset_ids() == frozenset({"first", "second"})
        assert requests.count("/api/search/metadata") == 2
        assert "/api/assets/first" not in requests


def test_generated_details_overlap_without_unbounded_http_requests():
    import time

    active = 0
    maximum = 0
    lock = threading.Lock()
    overlap = threading.Barrier(2, timeout=2)

    def detail():
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        try:
            overlap.wait()
            time.sleep(0.01)
            return {"tags": [{"value": "immich-memories/generated"}]}
        finally:
            with lock:
                active -= 1

    assets = {
        "/api/search/metadata": {"assets": {"items": [{"id": str(i)} for i in range(16)]}},
        **{f"/api/assets/{i}": detail for i in range(16)},
    }
    with (
        permission_server(list(READ_PERMISSIONS), assets=assets) as (url, _requests),
        SyncImmichClient(url, "synthetic-key") as client,
    ):
        assert client.generated_asset_ids() == frozenset(str(i) for i in range(16))
    assert 2 <= maximum <= 8


@pytest.mark.asyncio
async def test_generated_detail_failure_refuses_to_return_partial_exclusions():
    from immich_memories.api.generated_asset_tags import generated_asset_ids

    async def request(method, path, **_kwargs):
        if method == "POST":
            return {"assets": {"items": [{"id": "known"}, {"id": "unreadable"}]}}
        if path.endswith("unreadable"):
            raise RuntimeError("asset detail refused")
        return {"tags": [{"value": "immich-memories/generated"}]}

    with pytest.raises(RuntimeError, match="asset detail refused"):
        await generated_asset_ids(request, can_read_tags=False)
