"""A household run reads each picture through the account that can open it (#1500 slice 5).

One fake Immich server, two synthetic accounts. The primary key is refused every read of a
picture the partner owns (its original, preview and Live Photo motion), as a partner-only
upload is, so only the partner's own client can put that picture in the film.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from immich_memories.analysis.editorial_runtime import EditorialRunContext, build_editorial_planner
from immich_memories.analysis.editorial_runtime_ports import EditorialRuntimePorts
from immich_memories.analysis.selection_source import prepare_editorial_source
from immich_memories.api.access_clients import AccessBoundClient, AccountReadFailed, reads_for
from immich_memories.api.compatibility import ApiVersionPolicy
from immich_memories.api.models import Asset
from immich_memories.api.sync_client import SyncImmichClient
from immich_memories.config import Config
from immich_memories.generate_downloads import _download_temporary_asset
from immich_memories.processing.download_coordinator import (
    DownloadCoordinator,
    build_sync_client_factory,
)
from immich_memories.timeperiod import DateRange

URL = "https://immich.example.test"
PRIMARY_KEY = "primary-" * 4
PARTNER_KEY = "partner-" * 4
USERS = {PRIMARY_KEY: "user-primary", PARTNER_KEY: "user-partner"}
WINDOW = DateRange(datetime(2025, 6, 1, tzinfo=UTC), datetime(2025, 6, 30, 23, 59, tzinfo=UTC))
_ASSET_READ = re.compile(r"/api/assets/([^/]+)(/original|/thumbnail|/video/playback)?$")


def _sha1(content: str) -> str:
    return base64.b64encode(hashlib.sha1(content.encode(), usedforsecurity=False).digest()).decode()


def _asset(asset_id: str, owner: str, *, favourite=False, bytes_of="", companion=None) -> dict:
    taken = datetime(2025, 6, 3, 12, tzinfo=UTC).isoformat()
    return {
        "id": asset_id,
        "ownerId": owner,
        "type": "IMAGE" if companion else "VIDEO",
        "originalFileName": f"{asset_id}.MOV",
        "fileCreatedAt": taken,
        "fileModifiedAt": taken,
        "updatedAt": taken,
        "isFavorite": favourite,
        "width": 1920,
        "height": 1080,
        "duration": "0:00:05.000",
        "checksum": _sha1(bytes_of or asset_id),
        "livePhotoVideoId": companion,
    }


@dataclass
class FakeImmich:
    library: dict[str, list[dict]] = field(default_factory=dict)
    owners: dict[str, str] = field(default_factory=dict)
    # Every picture read: (whose key asked, which asset, whether it was served).
    reads: list[tuple[str, str, bool]] = field(default_factory=list)
    # Keys that still prove who they are but whose picture reads now fail.
    revoked: set[str] = field(default_factory=set)

    def hold(self, key: str, *assets: dict) -> None:
        self.library.setdefault(key, []).extend(assets)
        self.owners.update({asset["id"]: asset["ownerId"] for asset in assets})

    def reads_of(self, asset_id: str) -> list[tuple[str, bool]]:
        return [(user, served) for user, read, served in self.reads if read == asset_id]


@pytest.fixture
def immich(monkeypatch) -> FakeImmich:
    server = FakeImmich()
    real_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        key = request.headers["x-api-key"]
        user = USERS[key]
        if request.url.path.endswith("/users/me"):
            return httpx.Response(200, json={"id": user, "email": f"{user}@x.test"})
        if request.url.path.endswith("/search/metadata"):
            wanted = json.loads(request.content)["type"]
            items = [item for item in server.library.get(key, []) if item["type"] == wanted]
            return httpx.Response(200, json={"assets": {"items": items, "total": len(items)}})
        read = _ASSET_READ.search(request.url.path)
        if read is None:
            return httpx.Response(200, json=[])
        asset_id = read.group(1)
        served = server.owners.get(asset_id) == user and key not in server.revoked
        server.reads.append((user, asset_id, served))
        if not served:
            return httpx.Response(403, json={"message": "Not found or no asset.read access"})
        return httpx.Response(200, content=f"bytes-of-{asset_id}".encode())

    # WHY: the HTTP boundary; every Immich request goes to the in-process fake server above.
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    return server


def _config(tmp_path) -> Config:
    return Config(
        immich={
            "url": URL,
            "api_key": PRIMARY_KEY,
            "api_version": "v2",
            "accounts": {"partner": {"url": URL, "api_key": PARTNER_KEY, "api_version": "v2"}},
        },
        llm={"model": "no-model-calls"},
        cache={"directory": str(tmp_path / "cache")},
    )


@pytest.fixture
def run(tmp_path, immich):
    """A household run's client, and its source step handing the editor the folded pool."""
    client = AccessBoundClient(_config(tmp_path).immich)

    def source(accounts=("primary", "partner")) -> dict[str, Asset]:
        config = _config(tmp_path)
        context = EditorialRunContext(
            key="household",
            label="June",
            product="month",
            date_ranges=(WINDOW,),
            target_seconds=60,
            artifact_dir=tmp_path / "attempt",
            accounts=accounts,
        )
        planner = build_editorial_planner(
            client=client,
            thumbnail_cache=object(),
            context=context,
            config=config,
            ports=EditorialRuntimePorts(load_people=lambda: {}),
        )._planner
        prepared = prepare_editorial_source(
            planner._selection_request,
            replace(planner._source_dependencies, preview_jpeg=None),
            group=False,
        )
        return {candidate.asset_id: candidate.source for candidate in prepared.candidates}

    yield client, source
    client.close()


def _render_downloads(client: SyncImmichClient, assets, output_dir: Path) -> dict:
    """What the render's download step does with the run's client: one worker per source."""
    coordinator = DownloadCoordinator(
        build_sync_client_factory(client, ApiVersionPolicy.V2),
        None,
        2,
        download_operation=lambda worker, asset: _download_temporary_asset(
            worker, asset, output_dir
        ),
    )
    return coordinator.prefetch(assets)


def test_a_one_account_run_reads_every_picture_through_the_primary_as_before(tmp_path, immich, run):
    immich.hold(PRIMARY_KEY, _asset("own-video", "user-primary"))
    client, source = run
    pool = source(accounts=())

    results = _render_downloads(client, pool.values(), tmp_path / "out")

    assert results["own-video"].path is not None
    assert immich.reads_of("own-video") == [("user-primary", True)]
    assert "access_accounts" not in pool["own-video"].model_dump(mode="json")
    stage = reads_for(_config(tmp_path).immich, pool.values())
    stage.close()
    assert type(stage) is SyncImmichClient


def test_a_partner_starred_copy_is_the_one_kept_and_downloads_through_the_partner(
    tmp_path, immich, run
):
    immich.hold(PRIMARY_KEY, _asset("own-video", "user-primary", bytes_of="beach"))
    immich.hold(PARTNER_KEY, _asset("copy-video", "user-partner", bytes_of="beach", favourite=True))
    client, source = run
    pool = source()

    results = _render_downloads(client, pool.values(), tmp_path / "out")

    assert set(pool) == {"copy-video"}
    assert results["copy-video"].path.read_bytes() == b"bytes-of-copy-video"
    assert immich.reads_of("copy-video") == [("user-partner", True)]


def test_with_no_star_the_primary_s_copy_is_kept_and_read_through_the_primary(
    tmp_path, immich, run
):
    # The partner's owner id sorts first, so without the primary's user this tie went to it.
    immich.hold(PRIMARY_KEY, _asset("own-video", "user-primary", bytes_of="beach"))
    immich.hold(PARTNER_KEY, _asset("copy-video", "user-partner", bytes_of="beach"))
    client, source = run
    pool = source()

    _render_downloads(client, pool.values(), tmp_path / "out")

    assert set(pool) == {"own-video"}
    assert immich.reads_of("own-video") == [("user-primary", True)]
    assert immich.reads_of("copy-video") == []


def test_a_partner_s_live_photo_plays_its_motion_through_the_partner(tmp_path, immich, run):
    still = _asset("partner-still", "user-partner", companion="partner-motion")
    immich.hold(PARTNER_KEY, still)
    immich.owners["partner-motion"] = "user-partner"
    client, _source = run
    client.open_accounts(["primary", "partner"])
    live = Asset.model_validate(still).model_copy(
        update={"access_accounts": ("partner", "primary")}
    )
    client.routes.learn([live])

    results = _render_downloads(client, [live], tmp_path / "out")
    stage = reads_for(_config(tmp_path).immich, [live])
    try:
        # The planner's clock-offset and motion stages read the companion the same way.
        motion = stage.get_video_playback("partner-motion")
    finally:
        stage.close()

    assert results["partner-still"].download_id == "partner-motion"
    assert results["partner-still"].path is not None
    assert motion == b"bytes-of-partner-motion"
    assert {user for user, _ in immich.reads_of("partner-motion")} == {"user-partner"}
    assert client.get_asset_thumbnail("partner-still") == b"bytes-of-partner-still"


def test_an_owner_s_read_that_fails_mid_run_fails_the_attempt_naming_the_account(
    tmp_path, immich, run
):
    immich.hold(PRIMARY_KEY, _asset("shared-video", "user-partner", bytes_of="party"))
    immich.hold(PARTNER_KEY, _asset("shared-video", "user-partner", bytes_of="party"))
    client, source = run
    pool = source()
    immich.revoked.add(PARTNER_KEY)

    with pytest.raises(AccountReadFailed, match="'partner' could not read asset shared-video"):
        _render_downloads(client, pool.values(), tmp_path / "out")

    # The primary, which holds it through partner sharing, is never asked instead.
    assert immich.reads_of("shared-video") == [("user-partner", False)]
