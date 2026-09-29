"""A unit test that opens a store never shells out for the mount table.

On macOS the network-filesystem guard asks `/sbin/mount`, once per process. A suite that
forbids subprocesses (the timing tests do) then failed on a Mac and passed on Linux CI,
depending on which test happened to open a store first.
"""

from __future__ import annotations

import pytest

from immich_memories.db import network_guard
from immich_memories.db.sqlite_files import prepare_sqlite_file


def test_opening_a_store_on_a_mac_runs_no_mount_command(tmp_path, monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("a unit test ran a subprocess to read the mount table")

    network_guard._bsd_mounts.cache_clear()
    monkeypatch.setattr("subprocess.run", forbidden)
    # WHY: the macOS branch is the one that shells out; force it on a Linux runner too.
    monkeypatch.setattr(network_guard.sys, "platform", "darwin")

    prepare_sqlite_file(tmp_path / "store.db")
