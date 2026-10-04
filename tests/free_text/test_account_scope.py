"""What the asking accounts can see: the pool scope `--ask` reads before the funnel (#2044)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from immich_memories.db import open_store
from immich_memories.free_text.account_scope import (
    AccountScope,
    resolve_account_scope,
    visible_pictures,
)
from immich_memories.free_text.library import LibraryPicture


def _picture(asset_id: str) -> LibraryPicture:
    return LibraryPicture(
        asset_id=asset_id, taken_at=datetime(2020, 1, 1, tzinfo=UTC), media_kind="photo"
    )


def test_every_picture_is_visible_when_no_account_is_named() -> None:
    pictures = [_picture("a"), _picture("b")]

    assert visible_pictures(pictures, AccountScope()) == tuple(pictures)


def test_only_a_named_accounts_pictures_are_visible() -> None:
    pictures = [_picture("mine"), _picture("partners")]
    scope = AccountScope(picture_accounts={"mine": "primary"})

    assert {p.asset_id for p in visible_pictures(pictures, scope)} == {"mine"}


def test_resolving_the_scope_without_accounts_makes_no_request() -> None:
    store = open_store()

    scope = resolve_account_scope(object(), (), [_picture("a")], store)  # type: ignore[arg-type]

    assert scope == AccountScope()


def test_resolving_the_scope_with_no_pictures_makes_no_request() -> None:
    store = open_store()

    scope = resolve_account_scope(object(), ("partner",), [], store)  # type: ignore[arg-type]

    assert scope == AccountScope()


def test_a_request_naming_accounts_needs_an_access_bound_client() -> None:
    store = open_store()

    with pytest.raises(TypeError, match="AccessBoundClient"):
        resolve_account_scope(object(), ("partner",), [_picture("a")], store)  # type: ignore[arg-type]


def test_native_sharing_widens_a_face_accounts_entry_beyond_its_saved_binding(monkeypatch) -> None:
    """A person saved with one explicit binding (`primary` alone) can still be shared
    natively with the partner's own cluster (#2044, mirrors
    `test_native_cluster_identity_finds_the_partner_picture_without_a_second_binding`): the
    scope must hold the face to every account the cluster actually verifies, not just the
    account the people store happened to save."""
    from immich_memories.api.access_clients import AccessBoundClient
    from immich_memories.config_models import ImmichConfig
    from immich_memories.people.transfer import import_document
    from tests.household_fake import PARTNER_KEY, PRIMARY_KEY, FakeHousehold, immich_config, picture

    store = open_store()
    import_document(
        store,
        {
            "version": 1,
            "people": [
                {
                    "ids": ["shared"],
                    "name": "Alex",
                    "birth_date": None,
                    "inferred": {
                        "tier": "inner",
                        "counts_reliable": True,
                        "evidence": {},
                        "links": [],
                    },
                    "confirmed": {"role": None, "links": [], "notes": None},
                }
            ],
        },
    )
    FakeHousehold(
        library={
            PRIMARY_KEY: [picture("p-cat", "primary", 1, ("shared",))],
            PARTNER_KEY: [picture("q-cat", "partner", 2, ())],
        },
        roster={PRIMARY_KEY: [{"id": "shared", "name": "Alex"}], PARTNER_KEY: []},
        version={"major": 3, "minor": 2, "patch": 4},
        clusters={PRIMARY_KEY: "cluster", PARTNER_KEY: "cluster"},
    ).install(monkeypatch)
    config = ImmichConfig(**immich_config(), native_sharing=True)
    pictures = [_picture("p-cat"), _picture("q-cat")]

    with AccessBoundClient(config) as client:
        scope = resolve_account_scope(client, ("primary", "partner"), pictures, store)

    assert scope.face_accounts["shared"] == frozenset({"primary", "partner"})
