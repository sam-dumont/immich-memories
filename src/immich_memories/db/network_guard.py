"""Refuse a SQLite file on a network filesystem.

WAL keeps its index in shared memory beside the file, which NFS, SMB and CIFS cannot share
between hosts, and their byte-range locks are unreliable. Two writers there corrupt the
database quietly. `IMMICH_MEMORIES_ALLOW_NETWORK_SQLITE=1` downgrades the refusal to a
warning for the operator who knows only one host ever opens it.
"""

from __future__ import annotations

import functools
import logging
import os
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

logger = logging.getLogger(__name__)

OVERRIDE_ENV = "IMMICH_MEMORIES_ALLOW_NETWORK_SQLITE"
NETWORK_FILESYSTEMS = frozenset(
    {"nfs", "nfs4", "cifs", "smb", "smb2", "smb3", "smbfs", "afpfs", "webdav"}
)

Mounts = Sequence[tuple[str, str]]

_MOUNT_LINE = re.compile(r"^.+? on (?P<point>/.*?) \((?P<fstype>[^,)]+)")
_OCTAL_ESCAPE = re.compile(r"\\([0-7]{3})")


class NetworkFilesystemError(RuntimeError):
    """The SQLite file sits on a network filesystem and no override allows it."""


def parse_mountinfo(text: str) -> tuple[tuple[str, str], ...]:
    """(mount point, fstype) pairs from Linux `/proc/self/mountinfo`."""
    mounts = []
    for line in text.splitlines():
        fields, _, rest = line.partition(" - ")
        parts = fields.split()
        if len(parts) < 5 or not rest:
            continue
        point = _OCTAL_ESCAPE.sub(lambda m: chr(int(m.group(1), 8)), parts[4])
        mounts.append((point, rest.split()[0]))
    return tuple(mounts)


def parse_mount_output(text: str) -> tuple[tuple[str, str], ...]:
    """(mount point, fstype) pairs from BSD/macOS `mount` output."""
    return tuple(
        (match["point"], match["fstype"])
        for line in text.splitlines()
        if (match := _MOUNT_LINE.match(line))
    )


@functools.cache
def _bsd_mounts() -> tuple[tuple[str, str], ...]:
    # Read once per process: a store does not change filesystems while it is open.
    try:
        result = subprocess.run(
            ["/sbin/mount"], capture_output=True, text=True, timeout=10, check=True
        )
    except (OSError, subprocess.SubprocessError):
        logger.debug("could not list mounts; the network-filesystem guard is off")
        return ()
    return parse_mount_output(result.stdout)


def system_mounts() -> tuple[tuple[str, str], ...]:
    """This machine's mount table, or nothing where it cannot be read."""
    if sys.platform.startswith("linux"):
        try:
            return parse_mountinfo(Path("/proc/self/mountinfo").read_text())
        except OSError:
            return ()
    if sys.platform == "darwin" or "bsd" in sys.platform:
        return _bsd_mounts()
    return ()


def network_filesystem(path: str | os.PathLike[str], mounts: Mounts | None = None) -> str | None:
    """The network filesystem type holding `path`, or None when it is local."""
    target = os.path.realpath(path)
    best_point, best_type = "", ""
    for point, fstype in system_mounts() if mounts is None else mounts:
        inside = point in ("/", target) or target.startswith(point.rstrip("/") + "/")
        if inside and len(point) >= len(best_point):
            best_point, best_type = point, fstype
    return best_type if best_type.lower() in NETWORK_FILESYSTEMS else None


def guard_sqlite_path(path: str | os.PathLike[str], mounts: Mounts | None = None) -> None:
    """Raise when `path` is on a network filesystem, or only warn when the override is set."""
    fstype = network_filesystem(path, mounts)
    if fstype is None:
        return
    message = (
        f"the SQLite database {path} is on a network filesystem ({fstype}); WAL and file "
        "locks are unsafe there. Move it to a local disk, or point IMMICH_MEMORIES_DATABASE_URL "
        f"at PostgreSQL. Set {OVERRIDE_ENV}=1 only if one host ever opens it."
    )
    if os.environ.get(OVERRIDE_ENV) == "1":
        logger.warning(message)
        return
    raise NetworkFilesystemError(message)
