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
