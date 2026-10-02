"""Serve only the finished media file a trusted run record names."""

from pathlib import Path

from immich_memories.tracking.models import RunMetadata

FILM_TYPES = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
}


def local_film(record: RunMetadata) -> Path | None:
    """The record is the ownership boundary; custom CLI output directories remain valid.

    No browser-supplied filename is accepted. A symlink or non-film entry in a
    damaged record must not turn either the player or downloader into a file reader.
    """
    if not record.output_path:
        return None
    path = Path(record.output_path).expanduser()
    if path.suffix.lower() not in FILM_TYPES or ".." in path.parts or path.is_symlink():
        return None
    try:
        return path if path.is_file() and path.stat().st_size > 0 else None
    except OSError:
        return None
