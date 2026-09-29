"""A household run reads each chosen account (#1500 slice 3).

One fake Immich server, three synthetic accounts. The primary sees its own pictures plus
what the partner and grandma share with it; the partner sees its own. Only a run that
names its accounts reads more than the primary, and only pictures its chosen owners own.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx
import pytest

from immich_memories.analysis.editorial_runtime import EditorialRunContext, build_editorial_planner
from immich_memories.analysis.editorial_runtime_ports import EditorialRuntimePorts
from immich_memories.analysis.selection_source import (
    EditorialDependencies,
    EditorialSelectionRequest,
    prepare_editorial_source,
)
from immich_memories.api.access_clients import AccessBoundClient
from immich_memories.api.accounts import AccountUnavailable
from immich_memories.api.models import Asset
from immich_memories.config import Config
from immich_memories.db import open_store
from immich_memories.store.editorial_preparation import remember_assets
from immich_memories.timeperiod import DateRange

URL = "https://immich.example.test"
PRIMARY_KEY = "primary-" * 4
PARTNER_KEY = "partner-" * 4
GRANDMA_KEY = "grandma-" * 4
USERS = {PRIMARY_KEY: "user-primary", PARTNER_KEY: "user-partner", GRANDMA_KEY: "user-grandma"}
WINDOW = DateRange(datetime(2025, 6, 1, tzinfo=UTC), datetime(2025, 6, 30, 23, 59, tzinfo=UTC))


def _asset(
    asset_id: str, owner: str, day: int, *, kind="IMAGE", favourite=False, copy_of: str = ""
):
    taken = datetime(2025, 6, day, 12, tzinfo=UTC).isoformat()
    return {
        "id": asset_id,
        "ownerId": owner,
        "type": kind,
        "originalFileName": f"IMG_{day:04d}.{'MOV' if kind == 'VIDEO' else 'HEIC'}",
        "fileCreatedAt": taken,
        "fileModifiedAt": taken,
        "updatedAt": taken,
        "isFavorite": favourite,
        "width": 4032,
        "height": 3024,
        "duration": "0:00:05.000" if kind == "VIDEO" else None,
        "checksum": f"sum-{copy_of or asset_id}",
        "exifInfo": {"make": "Apple", "model": "iPhone"},
    }


# What each key's metadata search answers. Like a real household, the partner's library is
# mostly byte copies of the primary's, under its own IDs (collapsing those is slice 4's
# job), with a few pictures of its own. Some installs also share partner timelines: the
# partner's "shared" shows up in the primary's search, unstarred there though its owner
# starred it, and so does a picture from grandma, whom this film did not choose.
LIBRARY = {
    PRIMARY_KEY: [
        _asset("own-photo", "user-primary", 2),
        _asset("own-video", "user-primary", 3, kind="VIDEO"),
        _asset("shared", "user-partner", 4),
        _asset("grandma-photo", "user-grandma", 5),
    ],
    PARTNER_KEY: [
        _asset("copy-photo", "user-partner", 2, copy_of="own-photo"),
        _asset("copy-video", "user-partner", 3, kind="VIDEO", copy_of="own-video"),
        _asset("shared", "user-partner", 4, favourite=True),
        _asset("partner-photo", "user-partner", 6),
    ],
}


@dataclass
class FakeImmich:
    searched_by: list[str] = field(default_factory=list)
    # Keys that pass /users/me but whose library read is refused: a key missing asset.read.
    refusing_search: set[str] = field(default_factory=set)


@pytest.fixture
def immich_server(monkeypatch) -> FakeImmich:
    """One fake Immich: /users/me per key, and a metadata search per key's library."""
    server = FakeImmich()
    real_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        key = request.headers["x-api-key"]
        if request.url.path.endswith("/users/me"):
            return httpx.Response(200, json={"id": USERS[key], "email": f"{USERS[key]}@x.test"})
        if not request.url.path.endswith("/search/metadata"):
            return httpx.Response(200, json=[])
        if key in server.refusing_search:
            return httpx.Response(403, json={"message": "Missing permission: asset.read"})
        wanted = json.loads(request.content)["type"]
        server.searched_by.append(USERS[key])
        items = [item for item in LIBRARY.get(key, []) if item["type"] == wanted]
        return httpx.Response(200, json={"assets": {"items": items, "total": len(items)}})

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
            "accounts": {
                "partner": {"url": URL, "api_key": PARTNER_KEY, "api_version": "v2"},
                "grandma": {"url": URL, "api_key": GRANDMA_KEY, "api_version": "v2"},
            },
        },
        llm={"model": "no-model-calls"},
        cache={"directory": str(tmp_path / "cache")},
    )


def _source(tmp_path, accounts: tuple[str, ...] = ()):
    """What the run's source step hands the editor, coalesced as the editor coalesces it."""
    config = _config(tmp_path)
    context = EditorialRunContext(
        key="household",
        label="June",
        product="month",
        date_ranges=(WINDOW,),
        target_seconds=60,
        artifact_dir=tmp_path / "runs",
        accounts=accounts,
    )
    primary = AccessBoundClient(config.immich)
    try:
        planner = build_editorial_planner(
            client=primary,
            thumbnail_cache=object(),
            context=context,
            config=config,
            ports=EditorialRuntimePorts(load_people=lambda: {}),
        )
        request = planner._planner._selection_request
        fetcher = planner._planner._source_dependencies.source_fetcher
        prepared = prepare_editorial_source(
            EditorialSelectionRequest(scope=request.scope),
            EditorialDependencies(source_fetcher=fetcher),
            group=False,
        )
    finally:
        primary.close()
    return prepared.candidates


def _by_id(candidates) -> dict:
    return {candidate.asset_id: candidate for candidate in candidates}


def test_a_run_that_names_no_accounts_reads_the_primary_as_before(tmp_path, immich_server):
    source = _by_id(_source(tmp_path))

    assert set(source) == {"own-photo", "own-video", "shared", "grandma-photo"}
    assert set(immich_server.searched_by) == {"user-primary"}
    assert all(candidate.source.access_accounts == () for candidate in source.values())
    assert "access_accounts" not in source["shared"].source.model_dump(mode="json")


def test_a_household_run_reads_each_chosen_account_and_tags_who_returned_it(
    tmp_path, immich_server
):
    source = _by_id(_source(tmp_path, ("primary", "partner")))

    assert source["own-photo"].source.access_accounts == ("primary",)
    assert source["own-video"].source.access_accounts == ("primary",)
    assert source["partner-photo"].source.access_accounts == ("partner",)
    assert sorted(immich_server.searched_by) == ["user-partner"] * 2 + ["user-primary"] * 2


@pytest.mark.parametrize("accounts", [("primary", "partner"), ("partner", "primary")])
def test_a_picture_shared_between_partners_is_one_picture_both_can_open(
    tmp_path, immich_server, accounts
):
    candidates = _source(tmp_path, accounts)

    [shared] = [candidate for candidate in candidates if candidate.asset_id == "shared"]
    # Its owner is the partner, so the partner's account leads whichever account read it
    # first; the star the owner set survives the primary's unstarred copy.
    assert shared.source.access_accounts == ("partner", "primary")
    assert shared.favourite is True


def test_a_picture_shared_by_an_account_the_run_did_not_choose_stays_out(tmp_path, immich_server):
    source = _by_id(_source(tmp_path, ("primary", "partner")))

    assert "grandma-photo" not in source
    assert {"own-photo", "shared", "partner-photo"} <= set(source)
    assert "user-grandma" not in immich_server.searched_by


def test_an_account_whose_read_fails_fails_the_run_naming_it(tmp_path, immich_server):
    immich_server.refusing_search.add(PARTNER_KEY)

    with pytest.raises(AccountUnavailable, match="'partner' could not be read") as failed:
        _source(tmp_path, ("primary", "partner"))

    assert PARTNER_KEY not in str(failed.value)


def test_an_account_that_cannot_prove_who_it_is_fails_the_run_before_any_read(
    tmp_path, immich_server
):
    with pytest.raises(AccountUnavailable, match="'uncle' is not configured"):
        _source(tmp_path, ("primary", "uncle"))

    assert immich_server.searched_by == []


def _byte_copy(asset_id: str, owner: str, *, favourite: bool) -> dict:
    """One account's upload of the same file: its own ID and star, the file's real SHA-1."""
    digest = hashlib.sha1(b"beach.heic").digest()  # noqa: S324 - Immich's checksum, not security
    return {
        **_asset(asset_id, owner, 7, favourite=favourite),
        "checksum": base64.b64encode(digest).decode(),
    }


@pytest.mark.parametrize("accounts", [("primary", "partner"), ("partner", "primary")])
@pytest.mark.parametrize(
    ("starred_by", "kept"), [("user-primary", "own-beach"), ("user-partner", "copy-beach")]
)
def test_a_star_on_either_owners_copy_is_the_copy_the_film_keeps(
    tmp_path, immich_server, monkeypatch, accounts, starred_by, kept
):
    """Both accounts uploaded the file and one owner starred theirs: that copy stands for it."""
    # WHY: each fake account's library answers with one byte copy of the same file.
    monkeypatch.setitem(
        LIBRARY,
        PRIMARY_KEY,
        [_byte_copy("own-beach", "user-primary", favourite=starred_by == "user-primary")],
    )
    monkeypatch.setitem(
        LIBRARY,
        PARTNER_KEY,
        [_byte_copy("copy-beach", "user-partner", favourite=starred_by == "user-partner")],
    )

    [picture] = _source(tmp_path, accounts)

    assert picture.asset_id == kept
    assert picture.favourite is True


def test_what_the_store_banked_never_unstars_a_later_run(tmp_path, immich_server):
    """The store's favourite column is not evidence: every run reads the owners' stars live.

    A one-account `prepare` banks the partner's picture as the primary's search showed it,
    unstarred, around the pictures a household run kept. The next run keeps the owner's star.
    """
    first = _source(tmp_path, ("primary", "partner"))
    shared_as_the_primary_saw_it = Asset.model_validate(LIBRARY[PRIMARY_KEY][2])
    assert shared_as_the_primary_saw_it.is_favorite is False
    store = open_store()
    remember_assets(store, [shared_as_the_primary_saw_it])
    remember_assets(store, [candidate.source for candidate in first])
    remember_assets(store, [shared_as_the_primary_saw_it])

    later = _by_id(_source(tmp_path, ("primary", "partner")))

    assert later["shared"].favourite is True
    assert {c.asset_id: c.favourite for c in first} == {a: c.favourite for a, c in later.items()}
