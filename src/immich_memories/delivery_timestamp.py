"""When a finished memory happened, and how that instant is written down.

A memory is a stretch of days that ends somewhere. The render day says nothing
about it, so both the container tags and the Immich upload fields are stamped
with the memory's own last moment instead.
"""

from __future__ import annotations

import os
import struct
from collections import Counter
from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING, BinaryIO

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from pathlib import Path

    from immich_memories.api.models import Asset

__all__ = [
    "CARRY_CONTAINER_METADATA",
    "DROP_DEMUXED_TAGS",
    "capture_metadata_args",
    "carry_capture_instant",
    "film_capture_instant",
    "stamp_capture_instant",
]

_QUARTER_HOUR = timedelta(minutes=15)

# What FFmpeg's demuxer reports from an input's movie header and file type
# box. `use_metadata_tags` writes every key the output is given into the Keys
# list, so passed on these would sit in the film twice, beside the header the
# muxer writes anyway, and FFmpeg 7+ reads such a pair back as "a;b".
DROP_DEMUXED_TAGS: tuple[str, ...] = (
    "-metadata",
    "creation_time=",
    "-metadata",
    "major_brand=",
    "-metadata",
    "minor_version=",
    "-metadata",
    "compatible_brands=",
)

# A later FFmpeg pass over a finished film (the music mix) rebuilds the
# container, and a complex filtergraph switches off FFmpeg's own default
# metadata mapping, so the capture tag is mapped across by hand. The pass's
# caller restores the movie header with `carry_capture_instant`.
CARRY_CONTAINER_METADATA: tuple[str, ...] = (
    "-map_metadata",
    "0",
    *DROP_DEMUXED_TAGS,
    "-movflags",
    "+use_metadata_tags",
)

# ISO BMFF dates count seconds from 1904 in the movie, track and media headers,
# each a full box opening with version, flags, creation and modification time.
_MP4_EPOCH = datetime(1904, 1, 1, tzinfo=UTC)
_DATED_BOXES = frozenset({b"mvhd", b"tkhd", b"mdhd"})
_DATED_PARENTS = frozenset({b"moov", b"trak", b"mdia"})
_MAX_32_BIT = 0xFFFFFFFF


def _asset_offset(asset: Asset) -> timedelta | None:
    """The UTC offset the picture was shot at, or None when nothing says."""
    local = asset.local_date_time
    if local is not None:
        naive_local = local.replace(tzinfo=UTC) if local.tzinfo is None else local
        raw = naive_local - asset.file_created_at
        return _QUARTER_HOUR * round(raw / _QUARTER_HOUR)

    original = asset.exif_info.date_time_original if asset.exif_info else None
    if original is not None:
        return original.utcoffset()
    return None


def film_capture_instant(assets: Iterable[Asset]) -> datetime | None:
    """The capture instant a finished memory should be filed under.

    The memory is filed on the day of its **last** picture, told in the timezone
    **most** of its pictures were shot in — so a trip abroad still lands in the
    timeline where the rest of the memory sits.

    A picture's offset is ``localDateTime - fileCreatedAt`` rounded to the
    quarter hour (every real zone is a multiple of one), or the offset EXIF's
    ``dateTimeOriginal`` carries when Immich reports no local clock. Offsets are
    counted; the most common one wins, ties going to the one whose own pictures
    run latest. "Last" is by local wall clock.

    Returns None when no picture carries a usable time, which leaves the caller
    on its previous behaviour — for an upload, the render day.
    """
    dated = [
        (asset.file_created_at + offset, asset.file_created_at, offset)
        for asset in assets
        if (offset := _asset_offset(asset)) is not None
    ]
    if not dated:
        return None

    counts = Counter(offset for _, _, offset in dated)
    latest_per_offset = {
        offset: max(wall for wall, _, own in dated if own == offset) for offset in counts
    }
    modal_offset = max(counts, key=lambda offset: (counts[offset], latest_per_offset[offset]))

    last_instant = max(dated)[1]
    return last_instant.astimezone(timezone(modal_offset))


def capture_metadata_args(captured_at: datetime | None) -> list[str]:
    """FFmpeg ``-metadata`` arguments stamping a film with its local capture time.

    The QuickTime key keeps the offset, which is what Immich's exiftool pass
    reads to recover the local time and zone; FFmpeg only writes it with
    ``-movflags +use_metadata_tags``. The UTC instant goes into the movie header
    afterwards (`stamp_capture_instant`): passed here as ``creation_time`` it
    would be written a second time into the Keys list.
    """
    if captured_at is None:
        return []
    local = captured_at.replace(microsecond=0)
    return ["-metadata", f"com.apple.quicktime.creationdate={local.isoformat()}"]


def _boxes(handle: BinaryIO, start: int, end: int) -> Iterator[tuple[bytes, int, int]]:
    """Each box between ``start`` and ``end``: its type, payload start and end."""
    position = start
    while position + 8 <= end:
        handle.seek(position)
        size, kind = struct.unpack(">I4s", handle.read(8))
        header = 8
        if size == 1:
            (size,) = struct.unpack(">Q", handle.read(8))
            header = 16
        elif size == 0:
            size = end - position
        if size < header:
            return
        yield kind, position + header, position + size
        position += size


def _dated_payloads(handle: BinaryIO, start: int, end: int) -> Iterator[tuple[bytes, int]]:
    for kind, payload, box_end in _boxes(handle, start, end):
        if kind in _DATED_BOXES:
            yield kind, payload
        elif kind in _DATED_PARENTS:
            yield from _dated_payloads(handle, payload, box_end)


def _header_layout(handle: BinaryIO, payload: int) -> str:
    handle.seek(payload)
    return ">QQ" if handle.read(1) == b"\x01" else ">II"


def _write_header_times(film: Path, seconds: int) -> None:
    with film.open("r+b") as handle:
        end = handle.seek(0, os.SEEK_END)
        for _kind, payload in list(_dated_payloads(handle, 0, end)):
            layout = _header_layout(handle, payload)
            if layout == ">II" and seconds > _MAX_32_BIT:
                continue
            handle.seek(payload + 4)
            handle.write(struct.pack(layout, seconds, seconds))


def _movie_header_seconds(film: Path) -> int:
    with film.open("rb") as handle:
        end = handle.seek(0, os.SEEK_END)
        for kind, payload in _dated_payloads(handle, 0, end):
            if kind == b"mvhd":
                layout = _header_layout(handle, payload)
                handle.seek(payload + 4)
                return struct.unpack(layout, handle.read(struct.calcsize(layout)))[0]
    return 0


def stamp_capture_instant(film: Path, captured_at: datetime | None) -> None:
    """Write the capture instant into a finished film's movie, track and media headers.

    This is the film's one ``creation_time``, the UTC instant players and
    ffprobe read. It is patched in place: FFmpeg's only way to set it, a
    ``creation_time`` key, also copies it into the Keys list once
    ``use_metadata_tags`` is on.
    """
    if captured_at is None or not film.is_file():
        return
    _write_header_times(film, int((captured_at - _MP4_EPOCH).total_seconds()))


def carry_capture_instant(source: Path, film: Path) -> None:
    """Give a film rebuilt from ``source`` (a music mix) the source's header instant."""
    if not (source.is_file() and film.is_file()):
        return
    seconds = _movie_header_seconds(source)
    if seconds:
        _write_header_times(film, seconds)
