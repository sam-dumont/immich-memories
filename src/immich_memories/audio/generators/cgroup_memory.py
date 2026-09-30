"""Remaining container memory from the process's actual controller membership."""

from pathlib import Path, PurePosixPath


def _clean_inactive_bytes(directory: Path, *, v2: bool) -> int:
    try:
        counters = dict(row.split() for row in (directory / "memory.stat").read_text().splitlines())
        names = (
            (
                "file",
                "inactive_file",
                "shmem",
                "file_mapped",
                "file_dirty",
                "file_writeback",
                "unevictable",
            )
            if v2
            else (
                "cache",
                "inactive_file",
                "shmem",
                "mapped_file",
                "dirty",
                "writeback",
                "unevictable",
            )
        )
        prefix = "total_" if not v2 and "total_cache" in counters else ""
        file, inactive, *unavailable = (int(counters[prefix + name]) for name in names)
    except (OSError, ValueError, KeyError):
        return 0
    # Credit only inactive pages bounded by clean, unmapped, non-shared file cache.
    # The kernel reclaims these at memory.max; anonymous allocations remain occupied.
    if min(file, inactive, *unavailable) < 0:
        return 0
    return min(inactive, max(0, file - sum(unavailable)))


def _remaining(directory: Path, *, v2: bool) -> int | None:
    limit_name, usage_name = (
        ("memory.max", "memory.current")
        if v2
        else ("memory.limit_in_bytes", "memory.usage_in_bytes")
    )
    try:
        limit = int((directory / limit_name).read_text().strip())
        used = int((directory / usage_name).read_text().strip())
    except (OSError, ValueError):
        return None
    # v1's near-2**63 sentinel is unlimited, rather than usable memory.
    if limit >= 2**60 or limit < 0 or used < 0:
        return None
    return min(limit, max(0, limit - used + _clean_inactive_bytes(directory, v2=v2)))


def _memberships(proc: Path) -> dict[bool, PurePosixPath]:
    try:
        rows = (proc / "self/cgroup").read_text().splitlines()
    except OSError:
        return {}
    found = {}
    for row in rows:
        parts = row.split(":", 2)
        if len(parts) != 3:
            continue
        if not parts[1] or "memory" in parts[1].split(","):
            found[not parts[1]] = PurePosixPath(parts[2])
    return found


def _memory_mount(row: str) -> tuple[PurePosixPath, Path, bool] | None:
    before, separator, after = row.partition(" - ")
    fields, filesystem = before.split(), after.split()
    if not separator or len(fields) < 5 or len(filesystem) < 3:
        return None
    v2 = filesystem[0] == "cgroup2"
    if not v2 and (filesystem[0] != "cgroup" or "memory" not in filesystem[2].split(",")):
        return None
    return PurePosixPath(fields[3]), Path(fields[4]), v2


def _mounted_groups(root: Path, proc: Path) -> list[tuple[Path, Path, bool]]:
    memberships = _memberships(proc)
    try:
        mounts = (proc / "self/mountinfo").read_text().splitlines()
    except OSError:
        return []
    groups = []
    for row in mounts:
        mapping = _memory_mount(row)
        if mapping is None:
            continue
        mounted_root, mount, v2 = mapping
        member = memberships.get(v2)
        if member is None or not mount.is_relative_to(root):
            continue
        relative = (
            member.relative_to(mounted_root)
            if member.is_relative_to(mounted_root)
            else member.relative_to("/")
        )
        if ".." not in relative.parts:
            groups.append((mount, mount / str(relative), v2))
    return groups


def remaining_memory_bytes(root: Path, proc: Path) -> int | None:
    """The lowest finite headroom visible at the controller mount or process group."""
    candidates = [_remaining(root, v2=True), _remaining(root / "memory", v2=False)]
    for mount, group, v2 in _mounted_groups(root, proc):
        while group.is_relative_to(mount):
            candidates.append(_remaining(group, v2=v2))
            if group == mount:
                break
            group = group.parent
    bounded = [value for value in candidates if value is not None]
    return min(bounded) if bounded else None
