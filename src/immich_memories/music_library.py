"""The music-v3 library: pinned, fetched ahead of time, never at film time.

``immich-memories models fetch`` (and the Docker build) call ``install_music_v3``;
a film only calls ``installed_music_v3``, which reads the disk and nothing else.
The archive is digest-pinned like the model artifacts, unpacked into a scratch
folder next to its destination and renamed into place, so a half-written library
never looks installed.
"""

from __future__ import annotations

import logging
import os
import shutil
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

from immich_memories.pinned_models import MUSIC_V3, MUSIC_V3_MAX_BYTES, fetch_pinned_model

logger = logging.getLogger(__name__)

MUSIC_DIR_ENV = "IMMICH_MEMORIES_MUSIC_DIR"
MUSIC_V3_MOODS = ("calm", "tender", "nostalgic", "happy", "energetic")
MARKER = ".music-v3.sha256"
_ARCHIVE_ROOT = "music-v3"
_SUFFIXES = (".opus", ".mp3", ".m4a", ".flac", ".ogg", ".wav")
# 118 MB of Opus today; room for a later batch, not for a bomb.
MUSIC_UNPACKED_MAX_BYTES = 256 * 1024 * 1024
_CHUNK = 1024 * 1024


def music_v3_dir() -> Path:
    """Where the library lives: $IMMICH_MEMORIES_MUSIC_DIR, else ~/.immich-memories/models/music-v3."""
    configured = os.environ.get(MUSIC_DIR_ENV)
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".immich-memories" / "models" / "music-v3"


def installed_music_v3(
    directory: Path | None = None, *, sha256: str = MUSIC_V3.sha256
) -> Path | None:
    """The library folder when it is complete and was installed from the pinned archive."""
    root = directory or music_v3_dir()
    try:
        if (root / MARKER).read_text().strip() != sha256:
            return None
        for mood in MUSIC_V3_MOODS:
            folder = root / mood
            if not any(p.suffix.lower() in _SUFFIXES for p in folder.iterdir() if p.is_file()):
                return None
    except OSError:
        return None
    return root


def install_music_v3(
    destination: Path | None = None,
    *,
    url: str = MUSIC_V3.url,
    sha256: str = MUSIC_V3.sha256,
    force: bool = False,
    max_bytes: int = MUSIC_V3_MAX_BYTES,
) -> str:
    """Fetch, verify and unpack the library; ``"present"`` or ``"downloaded"``."""
    target = destination or music_v3_dir()
    if not force and installed_music_v3(target, sha256=sha256) is not None:
        return "present"
    target.parent.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
    try:
        archive = scratch / "music.tar"
        fetch_pinned_model(
            url=url, destination=archive, sha256=sha256, force=True, max_bytes=max_bytes
        )
        staged = scratch / "library"
        unpack_music(archive, staged)
        missing = [m for m in MUSIC_V3_MOODS if not _has_tracks(staged / m)]
        if missing:
            raise ValueError(f"the archive has no tracks for: {', '.join(missing)}")
        (staged / MARKER).write_text(sha256 + "\n")
        if target.exists():
            shutil.rmtree(target)
        staged.replace(target)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return "downloaded"


def _has_tracks(folder: Path) -> bool:
    return folder.is_dir() and any(p.suffix.lower() in _SUFFIXES for p in folder.iterdir())


def unpack_music(archive: Path, destination: Path) -> None:
    """Write the archive's ``music-v3/`` tree to ``destination``, refusing anything unsafe.

    The archive is digest-pinned, but a name that climbs out of the folder, a link or a
    device node is refused outright rather than skipped, and the unpacked size is capped.
    """
    root = destination.resolve()
    root.mkdir(parents=True, exist_ok=True)
    total = 0
    with tarfile.open(archive) as bundle:
        for member in bundle:
            target = _member_target(member, root)
            if target is None:
                continue
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            total += member.size
            if total > MUSIC_UNPACKED_MAX_BYTES:
                raise ValueError(f"refused past {MUSIC_UNPACKED_MAX_BYTES} unpacked bytes")
            _write_member(bundle, member, target)


def _member_target(member: tarfile.TarInfo, root: Path) -> Path | None:
    """Where a safe member lands; None for the archive root; ValueError for anything else."""
    relative = _relative_name(member.name)
    if relative is None:
        return None
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise ValueError(f"refused a path outside the library: {member.name}")
    if not (member.isdir() or member.isfile()):
        raise ValueError(f"refused a non-file entry: {member.name}")
    return target


def _write_member(bundle: tarfile.TarFile, member: tarfile.TarInfo, target: Path) -> None:
    source = bundle.extractfile(member)
    if source is None:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    with source, target.open("wb") as out:
        while chunk := source.read(_CHUNK):
            out.write(chunk)


def _relative_name(name: str) -> PurePosixPath | None:
    """The member's path below ``music-v3/``; None for the root itself."""
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"refused a path outside the library: {name}")
    parts = [p for p in path.parts if p != "."]
    if not parts or parts[0] != _ARCHIVE_ROOT:
        raise ValueError(f"refused an entry outside {_ARCHIVE_ROOT}/: {name}")
    return PurePosixPath(*parts[1:]) if len(parts) > 1 else None
