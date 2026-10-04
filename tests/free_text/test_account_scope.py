"""What the asking accounts can see: the pool scope `--ask` reads before the funnel (#2044)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from immich_memories.api.models import Asset
from immich_memories.db import open_store
from immich_memories.free_text.account_scope import (
    AccountScope,
    likely_household,
    resolve_account_scope,
    visible_pictures,
)
from immich_memories.free_text.library import LibraryPicture
from immich_memories.people.transfer import import_document
from immich_memories.store.editorial_preparation import remember_assets


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


def test_likely_household_is_true_when_the_config_names_another_account() -> None:
    store = open_store()

    assert likely_household(store, other_accounts=True, native_sharing=False) is True


def test_likely_household_is_true_when_native_sharing_is_on() -> None:
    store = open_store()

    assert likely_household(store, other_accounts=False, native_sharing=True) is True


def test_likely_household_is_true_for_a_non_primary_alias_with_no_other_signal() -> None:
    """A store written before the `household_seen` marker existed still carries this
    evidence in the people file (#2044): a name bound to a non-primary account alone is
    enough, with no account configured and no native sharing on."""
    store = open_store()
    import_document(
        store,
        {
            "version": 1,
            "people": [
                {
                    "ids": {"partner": ["kit-q"]},
                    "name": "Kit",
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

    assert likely_household(store, other_accounts=False, native_sharing=False) is True


def test_likely_household_defaults_true_for_an_untouched_legacy_store() -> None:
    """No config signal, no alias, and `remember_assets` has never run here: the store is
    scoped to the primary by default until an ownership-aware read actually confirms it."""
    store = open_store()

    assert likely_household(store, other_accounts=False, native_sharing=False) is True


def test_likely_household_is_false_once_a_read_confirms_a_single_account() -> None:
    store = open_store()
    remember_assets(
        store,
        [
            Asset(
                id="own",
                type="IMAGE",
                file_created_at=datetime(2024, 1, 1, tzinfo=UTC),
                file_modified_at=datetime(2024, 1, 1, tzinfo=UTC),
                updated_at=datetime(2024, 1, 1, tzinfo=UTC),
                original_file_name="own.jpg",
                width=10,
                height=10,
                access_accounts=("primary",),
            )
        ],
    )

    assert likely_household(store, other_accounts=False, native_sharing=False) is False


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
