"""A SQLite file on NFS, SMB or CIFS is refused: WAL needs shared memory those cannot give."""

from __future__ import annotations

import logging

import pytest

from immich_memories.db import NetworkFilesystemError, guard_sqlite_path, network_filesystem
from immich_memories.db.network_guard import parse_mount_output, parse_mountinfo

MOUNTS = (
    ("/", "ext4"),
    ("/mnt/nas", "nfs4"),
    ("/mnt/nas/local", "ext4"),
    ("/Volumes/share", "smbfs"),
    ("/srv/cifs", "cifs"),
)


@pytest.fixture(autouse=True)
def _no_override(monkeypatch):
    monkeypatch.delenv("IMMICH_MEMORIES_ALLOW_NETWORK_SQLITE", raising=False)


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        ("/mnt/nas/memories/store.db", "nfs4"),
        ("/Volumes/share/store.db", "smbfs"),
        ("/srv/cifs/deep/down/store.db", "cifs"),
        ("/mnt/nas/local/store.db", None),
        ("/home/me/.immich-memories/store.db", None),
        ("/mnt/nasty/store.db", None),
    ],
)
def test_the_deepest_mount_decides(path, kind):
    assert network_filesystem(path, mounts=MOUNTS) == kind


def test_a_network_file_is_refused_naming_the_override():
    with pytest.raises(NetworkFilesystemError, match="IMMICH_MEMORIES_ALLOW_NETWORK_SQLITE"):
        guard_sqlite_path("/mnt/nas/store.db", mounts=MOUNTS)


def test_the_override_downgrades_the_refusal_to_a_warning(monkeypatch, caplog):
    monkeypatch.setenv("IMMICH_MEMORIES_ALLOW_NETWORK_SQLITE", "1")

    with caplog.at_level(logging.WARNING):
        guard_sqlite_path("/mnt/nas/store.db", mounts=MOUNTS)

    assert "nfs4" in caplog.text


def test_a_local_file_passes_silently(caplog):
    with caplog.at_level(logging.WARNING):
        guard_sqlite_path("/home/me/store.db", mounts=MOUNTS)

    assert caplog.text == ""


def test_linux_mountinfo_is_read_with_escaped_spaces():
    text = (
        "22 1 8:1 / / rw,relatime shared:1 - ext4 /dev/sda1 rw\n"
        "40 22 0:50 / /mnt/my\\040nas rw,relatime shared:9 - nfs4 nas:/export rw,vers=4.2\n"
        "41 22 0:51 / /srv/x rw master:2 opt:3 - cifs //nas/x rw\n"
    )

    assert parse_mountinfo(text) == (
        ("/", "ext4"),
        ("/mnt/my nas", "nfs4"),
        ("/srv/x", "cifs"),
    )


def test_macos_mount_output_is_read():
    text = (
        "/dev/disk3s1s1 on / (apfs, sealed, local, read-only, journaled)\n"
        "//sam@nas._smb._tcp.local/photos on /Volumes/photos (smbfs, nodev, nosuid, mounted by sam)\n"
        "nas:/export on /private/nfs (nfs, asynchronous)\n"
    )

    assert parse_mount_output(text) == (
        ("/", "apfs"),
        ("/Volumes/photos", "smbfs"),
        ("/private/nfs", "nfs"),
    )


@pytest.mark.real_mounts
def test_this_machine_temp_dir_is_not_a_network_mount(tmp_path):
    guard_sqlite_path(tmp_path / "store.db")
