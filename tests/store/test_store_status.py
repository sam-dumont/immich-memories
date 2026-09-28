"""`store status`: what the store is, read without migrating or creating anything."""

from __future__ import annotations

from immich_memories.automation.state_store import AutomationStateStore
from immich_memories.db import StoreLocation, heads, open_store
from immich_memories.db.status import store_status


def test_status_reports_revision_counts_size_and_no_import_yet(location):
    AutomationStateStore(open_store(location=location)).start_attempt("one attempt")

    state = store_status(location)

    assert state.exists
    assert state.backend == location.dialect_name
    assert set(state.revisions) == set(heads())
    assert state.at_head
    assert state.counts["automation_attempts"] == 1
    assert state.size_bytes > 0
    assert state.import_record is None
    assert "***" in state.url or "@" not in state.url


def test_a_sqlite_store_that_does_not_exist_is_reported_and_not_created(tmp_path):
    path = tmp_path / "nowhere" / "store.db"

    state = store_status(StoreLocation(url=f"sqlite:///{path}"))

    assert not state.exists
    assert not path.exists()


def test_a_store_on_a_network_filesystem_is_flagged(tmp_path, monkeypatch):
    path = tmp_path / "store.db"
    open_store(location=StoreLocation(url=f"sqlite:///{path}"))
    # WHY: no NFS mount exists on a test runner; the mount table is the external boundary.
    monkeypatch.setattr("immich_memories.db.status.network_filesystem", lambda _path: "nfs")

    state = store_status(StoreLocation(url=f"sqlite:///{path}"))

    assert state.network_filesystem == "nfs"
