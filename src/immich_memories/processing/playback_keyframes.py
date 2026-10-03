"""A few keyframes of an Immich playback, read by byte range instead of downloaded whole.

Immich serves one playback rendition per video and answers range requests. The sample tables
in its `moov` say where every keyframe's bytes are, so a filmstrip costs the index and a few
keyframes (hundreds of kilobytes) instead of the whole rendition (tens of megabytes).

FFmpeg over the HTTP URL cannot be held to that: it reads forward instead of seeking whenever
the target is inside its read-ahead window, and its demuxer reads every packet, so three seeks
into a 10 MB clip transferred 10.5 MB. Here the fetched bytes are written at their own offsets
into a sparse local copy. FFmpeg then stream-copies only the packets at the fetched keyframes'
byte positions into a small NUT file and decodes that, so a zeroed sample never reaches a
decoder. `-discard nokey` looked like the shorter road and is not one: FFmpeg 5.1 and 8.1 honour
it on MP4, 6.1 (Ubuntu 24.04) decodes the zeroed samples anyway and gives up. The position
filter behaves the same on 5.1, 6.1, 7.1 and 8.1.
"""

from __future__ import annotations

import struct
import subprocess
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from statistics import median

import numpy as np

from immich_memories.processing.frame_sampling import even_timestamps

ReadRange = Callable[[int, int], tuple[bytes, int]]
"""Read ``length`` bytes at ``start``; answer them with the rendition's full size."""

HEAD_BYTES = 64 * 1024
MAX_INDEX_BYTES = 64 * 1024**2
# One keyframe cannot show action across time. A clip shorter than its encoder's GOP is also a
# small file, so reading it whole to sample evenly is cheaper than the second request it saves.
WHOLE_CLIP_LIMIT = 24 * 1024**2
MAX_TOP_LEVEL_BOXES = 64
_JPEG = "force_original_aspect_ratio=decrease:out_range=full,format=yuvj420p"
# Codecs whose stream parameters come from the sample description alone. For anything else
# FFmpeg's probe decodes the first sample, so that sample is fetched too (and never shown).
DESCRIBED_BY_INDEX = frozenset({"avc1", "avc3", "hvc1", "hev1", "vp09", "av01"})


@dataclass(frozen=True, slots=True)
class Keyframe:
    seconds: float
    offset: int
    size: int


@dataclass(frozen=True, slots=True)
class KeyframeIndex:
    keyframes: tuple[Keyframe, ...]
    duration: float
    codec: str


@dataclass(frozen=True, slots=True)
class SampledKeyframes:
    """JPEG frames in time order, and what reading them cost."""

    frames: tuple[bytes, ...]
    seconds: tuple[float, ...]
    duration: float
    bytes_read: int
    requests: int


def _boxes(data: bytes, start: int = 0, end: int | None = None) -> Iterator[tuple[bytes, int, int]]:
    """(kind, payload start, box end) for each box between ``start`` and ``end``."""
    at, end = start, len(data) if end is None else end
    while at + 8 <= end:
        size, kind = struct.unpack(">I4s", data[at : at + 8])
        header = 8
        if size == 1:
            size, header = struct.unpack(">Q", data[at + 8 : at + 16])[0], 16
        elif size == 0:
            size = end - at
        if size < header:
            raise ValueError("malformed MP4 box")
        yield kind, at + header, at + size
        at += size


def _child(data: bytes, span: tuple[int, int], kind: bytes) -> tuple[int, int]:
    for found, start, end in _boxes(data, *span):
        if found == kind:
            return start, end
    raise ValueError(f"MP4 index lacks {kind.decode()}")


def _table(data: bytes, stbl: tuple[int, int], kind: bytes) -> bytes | None:
    """A full box's payload after its version and flags, or None when it is absent."""
    for found, start, end in _boxes(data, *stbl):
        if found == kind:
            return data[start + 4 : end]
    return None


def _counted(payload: bytes | None, fmt: str) -> list[tuple[int, ...]]:
    """The rows of a counted table; an absent table has none."""
    if payload is None:
        return []
    width = struct.calcsize(fmt)
    count = struct.unpack(">I", payload[:4])[0]
    return [struct.unpack(fmt, payload[4 + i * width : 4 + (i + 1) * width]) for i in range(count)]


def _media(moov: bytes, handler: bytes) -> tuple[int, int]:
    for kind, start, end in _boxes(moov):
        if kind != b"trak":
            continue
        mdia = _child(moov, (start, end), b"mdia")
        hdlr = _child(moov, mdia, b"hdlr")
        if moov[hdlr[0] + 8 : hdlr[0] + 12] == handler:
            return mdia
    raise ValueError(f"MP4 index has no {'video' if handler == b'vide' else 'sound'} track")


def _sample_offsets(moov: bytes, stbl: tuple[int, int], sizes: list[int]) -> list[int]:
    chunks = [row[0] for row in _counted(_table(moov, stbl, b"stco"), ">I")] or [
        row[0] for row in _counted(_table(moov, stbl, b"co64"), ">Q")
    ]
    runs = _counted(_table(moov, stbl, b"stsc"), ">III")
    offsets: list[int] = []
    for index, (first, per_chunk, _description) in enumerate(runs):
        last = runs[index + 1][0] - 1 if index + 1 < len(runs) else len(chunks)
        for chunk in chunks[first - 1 : last]:
            for _ in range(per_chunk):
                offsets.append(chunk)
                chunk += sizes[len(offsets) - 1]
    return offsets


def _codec(moov: bytes, stbl: tuple[int, int]) -> str:
    """The first sample entry's four-character code, or empty when the index has none."""
    stsd = _table(moov, stbl, b"stsd")
    if stsd is None or len(stsd) < 12:
        return ""
    return stsd[8:12].decode("latin-1")


@dataclass(frozen=True, slots=True)
class _Track:
    """Every video sample's time, byte offset and size, and which ones are keyframes."""

    seconds: list[float]
    offsets: list[int]
    sizes: list[int]
    sync: list[int]
    duration: float
    codec: str


def _track(moov: bytes, handler: bytes = b"vide") -> _Track:
    mdia = _media(moov, handler)
    mdhd = _child(moov, mdia, b"mdhd")
    timescale = struct.unpack(">I", moov[mdhd[0] + (20 if moov[mdhd[0]] == 1 else 12) :][:4])[0]
    stbl = _child(moov, _child(moov, mdia, b"minf"), b"stbl")
    times: list[int] = []
    clock = 0
    for count, delta in _counted(_table(moov, stbl, b"stts"), ">II"):
        times.extend(clock + delta * i for i in range(count))
        clock += count * delta
    stsz = _table(moov, stbl, b"stsz")
    if stsz is None or not timescale:
        raise ValueError("MP4 index lacks sample sizes or a timescale")
    uniform, count = struct.unpack(">II", stsz[:8])
    sizes = (
        [uniform] * count if uniform else list(struct.unpack(f">{count}I", stsz[8 : 8 + 4 * count]))
    )
    offsets = _sample_offsets(moov, stbl, sizes)
    stss = _table(moov, stbl, b"stss")
    sync = [row[0] - 1 for row in _counted(stss, ">I")] if stss else list(range(count))
    if len(offsets) < count or len(times) < count:
        raise ValueError("MP4 sample tables disagree")
    seconds = [time / timescale for time in times[:count]]
    return _Track(seconds, offsets[:count], sizes, sync, clock / timescale, _codec(moov, stbl))


def keyframes_of(moov: bytes) -> KeyframeIndex:
    """The video track's keyframes, its length in seconds and its codec, from a ``moov`` payload.

    Edit lists and composition offsets are ignored: the times place a filmstrip, they do not
    cut the film.
    """
    track = _track(moov)
    keys = tuple(Keyframe(track.seconds[n], track.offsets[n], track.sizes[n]) for n in track.sync)
    return KeyframeIndex(keys, track.duration, track.codec)


class _Reader:
    """Counts what the index and the frames cost, so the producer can report it."""

    def __init__(self, read: ReadRange) -> None:
        self._read = read
        self.bytes_read = 0
        self.requests = 0
        self.total = 0

    def __call__(self, start: int, length: int) -> bytes:
        data, self.total = self._read(start, length)
        self.bytes_read += len(data)
        self.requests += 1
        return data


def _box_at(read: _Reader, head: bytes, at: int) -> tuple[bytes, int, int]:
    """(kind, header length, box size) of the top-level box starting at ``at``."""
    header = _span(read, head, at, 16)
    size, kind = struct.unpack(">I4s", header[:8])
    if size == 1:
        return kind, 16, struct.unpack(">Q", header[8:16])[0]
    return kind, 8, size or read.total - at


def _span(read: _Reader, head: bytes, at: int, length: int) -> bytes:
    return head[at : at + length] if at + length <= len(head) else read(at, length)


def _index(read: _Reader) -> tuple[dict[int, bytes], bytes]:
    """What a local copy needs before any frame: every top-level box but the media payload.

    ``mdat`` keeps only its header. Writing the whole first request back would plant the
    start of the first keyframe too, and FFmpeg would decode a frame nobody chose.
    """
    head = read(0, HEAD_BYTES)
    pieces: dict[int, bytes] = {}
    moov, at = b"", 0
    for _ in range(MAX_TOP_LEVEL_BOXES):
        if at >= read.total:
            break
        kind, header, size = _box_at(read, head, at)
        whole = kind != b"mdat" and size <= MAX_INDEX_BYTES
        pieces[at] = _span(read, head, at, size if whole else header)
        if kind == b"moov":
            moov = pieces[at][header:]
        at += max(size, header)
    if not moov:
        raise ValueError("playback has no MP4 index")
    return pieces, moov


def _chosen(keyframes: tuple[Keyframe, ...], duration: float, count: int) -> list[Keyframe]:
    """The keyframe nearest each evenly spaced moment, each at most once, in time order."""

    def nearest(target: float) -> Keyframe:
        return min(keyframes, key=lambda keyframe: abs(keyframe.seconds - target))

    chosen = {nearest(target) for target in even_timestamps(duration, count)}
    return sorted(chosen, key=lambda keyframe: keyframe.seconds)


def _write(path: Path, pieces: dict[int, bytes], total: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as copy:
        for offset in sorted(pieces):
            copy.seek(offset)
            copy.write(pieces[offset])
        if copy.tell() < total:  # a hole up to the declared size; nothing is allocated
            copy.seek(total - 1)
            copy.write(b"\0")


def _ffmpeg(*arguments: str) -> None:
    subprocess.run(  # noqa: S603 - fixed argv, paths are not shell-interpreted
        ["ffmpeg", "-v", "error", "-y", *arguments], capture_output=True, timeout=120, check=False
    )


def _decode(
    source: Path, workdir: Path, width: int, *, rate: str = "", limit: int = 0
) -> tuple[bytes, ...]:
    for stale in workdir.glob("frame-*.jpg"):
        stale.unlink()
    frames = ["-frames:v", str(limit)] if limit else []
    _ffmpeg(
        "-i", str(source), "-an", "-sn", "-dn", "-fps_mode", "passthrough",
        "-vf", f"{rate}scale={width}:{width}:{_JPEG}", *frames, "-q:v", "3",
        str(workdir / "frame-%03d.jpg"),
    )  # fmt: skip
    return tuple(frame.read_bytes() for frame in sorted(workdir.glob("frame-*.jpg")))


def _decode_keyframes(
    copy: Path, workdir: Path, width: int, chosen: list[Keyframe]
) -> tuple[bytes, ...]:
    """Copy out the packets at the chosen byte positions, then decode only those."""
    keys = workdir / "keyframes.nut"
    kept = "+".join(f"eq(pos\\,{keyframe.offset})" for keyframe in chosen)
    _ffmpeg(
        "-i", str(copy), "-map", "0:v:0", "-c", "copy",
        "-bsf:v", f"noise=drop=not({kept})", "-f", "nut", str(keys),
    )  # fmt: skip
    frames = _decode(keys, workdir, width) if keys.exists() else ()
    keys.unlink(missing_ok=True)
    return frames


def sample_keyframes(read: ReadRange, *, count: int, width: int, workdir: Path) -> SampledKeyframes:
    """Up to ``count`` frames spread across the playback, fitted inside ``width`` pixels.

    Only the index and the chosen keyframes are requested. A clip with a single keyframe and
    a small file is read whole and sampled at even times instead. Raises ValueError when the
    playback is not an MP4 this can index, or when the frames do not decode one for one.
    """
    reader = _Reader(read)
    pieces, moov = _index(reader)
    index = keyframes_of(moov)
    keyframes, duration = index.keyframes, index.duration
    copy = workdir / "playback.mp4"
    if len(keyframes) < 2 and reader.total <= WHOLE_CLIP_LIMIT:
        _write(copy, {0: reader(0, reader.total)}, reader.total)
        rate = f"fps={count}/{max(duration, 0.1):.3f},"
        frames = _decode(copy, workdir, width, rate=rate, limit=count)
        seconds = tuple(even_timestamps(duration, len(frames)))
    else:
        chosen = _chosen(keyframes, duration, count)
        fetched = chosen if index.codec in DESCRIBED_BY_INDEX else [keyframes[0], *chosen]
        pieces.update({k.offset: reader(k.offset, k.size) for k in fetched})
        _write(copy, pieces, reader.total)
        frames = _decode_keyframes(copy, workdir, width, chosen)
        if len(frames) != len(chosen):
            raise ValueError(f"{len(chosen)} keyframes decoded as {len(frames)} frames")
        seconds = tuple(k.seconds for k in chosen)
    copy.unlink(missing_ok=True)
    if not frames:
        raise ValueError("playback decoded no frames")
    return SampledKeyframes(frames, seconds, duration, reader.bytes_read, reader.requests)


# Fine enough to place a window, coarse enough that a B-frame's spread evens out.
ACTIVITY_BIN_SECONDS = 0.5
AUDIO_RATE = 16000
# Phones interleave sound and picture frame by frame, so a span's audio is hundreds of
# chunks a few kilobytes apart. On the NAS each chunk is a disk seek (757 requests: 6.5 s);
# reading through a gap this small turns them into a few sequential reads instead.
COALESCE_GAP_BYTES = 2 * 1024**2
AUDIO_READERS = 4


class PlaybackIndex:
    """One playback's MP4 index, read once by byte range, and what it can answer cheaply.

    The picture side comes from the index alone; the sound side fetches only the audio
    chunks of the span asked for. Neither ever reads a picture.
    """

    def __init__(self, read: ReadRange) -> None:
        self._reader = _Reader(read)
        self._lock = threading.Lock()
        self._pieces, moov = _index(self._reader)
        self._video = _track(moov)
        try:
            self._audio: _Track | None = _track(moov, b"soun")
        except ValueError:
            self._audio = None

    @property
    def duration(self) -> float:
        return self._video.duration

    @property
    def bytes_read(self) -> int:
        return self._reader.bytes_read

    def activity(self) -> tuple[tuple[float, float], ...]:
        """How much each half second changes: the median size of its predicted frames.

        A predicted frame stores only what changed since the frames it refers to, so its
        size rises when something crosses a still shot. Keyframes hold a whole picture and
        say nothing about change, so they are left out.
        """
        keyframes = set(self._video.sync)
        by_bin: dict[int, list[int]] = {}
        samples = zip(self._video.seconds, self._video.sizes, strict=False)
        for sample, (second, size) in enumerate(samples):
            if sample not in keyframes:
                by_bin.setdefault(int(second / ACTIVITY_BIN_SECONDS), []).append(size)
        return tuple(
            (index * ACTIVITY_BIN_SECONDS, float(median(sizes)))
            for index, sizes in sorted(by_bin.items())
        )

    def audio(self, start: float, end: float, *, workdir: Path) -> np.ndarray | None:
        """The sound between ``start`` and ``end`` as 16 kHz mono, or None without a track.

        Only the audio chunks of the span are fetched, each by its own byte range, then
        decoded from a sparse copy that holds the index and those chunks alone.
        """
        track = self._audio
        if track is None:
            return None
        wanted = [
            (track.offsets[n], track.offsets[n] + track.sizes[n])
            for n, second in enumerate(track.seconds)
            if start - 1.0 <= second < end
        ]
        if not wanted:
            return None
        pieces = self._pieces.copy()
        with ThreadPoolExecutor(AUDIO_READERS) as pool:
            spans = _merged(wanted, gap=COALESCE_GAP_BYTES)
            for (first, _last), data in zip(spans, pool.map(self._fetch, spans), strict=True):
                pieces[first] = data
        workdir.mkdir(parents=True, exist_ok=True)
        copy = workdir / "sound.mp4"
        _write(copy, pieces, self._reader.total)
        decoded = subprocess.run(  # noqa: S603 - fixed argv, paths are not shell-interpreted
            [
                "ffmpeg", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}",
                "-i", str(copy), "-map", "0:a:0", "-ac", "1", "-ar", str(AUDIO_RATE),
                "-f", "f32le", "-",
            ],
            capture_output=True, timeout=120, check=False,
        )  # fmt: skip
        copy.unlink(missing_ok=True)
        usable = len(decoded.stdout) // 4 * 4
        return np.frombuffer(decoded.stdout[:usable], dtype=np.float32) if usable else None

    def _fetch(self, span: tuple[int, int]) -> bytes:
        data, total = self._reader._read(span[0], span[1] - span[0])
        with self._lock:
            self._reader.total = total
            self._reader.bytes_read += len(data)
            self._reader.requests += 1
        return data


def _merged(spans: list[tuple[int, int]], *, gap: int = 0) -> list[tuple[int, int]]:
    """Byte spans in order, the ones closer than ``gap`` joined into one request."""
    merged: list[list[int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1] + gap:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]
