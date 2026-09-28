"""The suite may open a store under any HOME except the account's own."""

from __future__ import annotations

import pytest

from immich_memories.db import engine as engine_module
from immich_memories.db.bootstrap import StoreLocation
from tests.conftest import _REAL_STORE_OPENS, _account_home


def test_a_store_under_a_disposable_home_opens(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    location = StoreLocation(url="sqlite:///~/.immich-memories/store.db", schema="immich_memories")

    engine = engine_module.create_store_engine(location)
    engine.dispose()

    assert _REAL_STORE_OPENS == []


def test_the_accounts_own_store_is_refused_before_it_connects():
    path = _account_home() / ".immich-memories" / "store.db"
    location = StoreLocation(url=f"sqlite:///{path}", schema="immich_memories")

    with pytest.raises(RuntimeError, match="developer's own store"):
        engine_module.create_store_engine(location)

    assert [str(path)] == _REAL_STORE_OPENS
    # Expected here: clear it so the autouse check does not fail this test.
    _REAL_STORE_OPENS.clear()
