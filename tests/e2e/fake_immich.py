"""Small deterministic Immich v3 HTTP service for hermetic E2E tests."""

from __future__ import annotations

import contextlib
import json
import subprocess
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import datetime
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Self
from urllib.parse import parse_qs, urlsplit

from tests.e2e.fake_library import (
    ALL_PICTURES,
    BURST_STEP_SECONDS,
    CAST,
    HOME,
    LIVE_CLIP_SECONDS,
    PARTNER_PICTURES,
    Picture,
)
from tests.immich_fakes import V2, V3, request_problems

_MONTH_BUCKET = "2024-06-01T00:00:00.000Z"

# WHY these three facts together (#525): selection drops a clip whose short
# side is under 1080 unless EXIF names a camera, drops a still that names no
# camera at all, and collapses assets whose thumbnails hash alike. A fixture
# that is small, EXIF-less and identical fails all three, and the release smoke
# test spent every run since #491 reporting "Pipeline selected no clips".
_CAMERA_EXIF = {"make": "FakeCam", "model": "Hermetic One"}
_VIDEO_SIZE = (1920, 1080)
_PHOTO_SIZE = (1920, 1280)
_VIDEO_DURATION = 4.0

# A still panned across for its four seconds, the way a phone pans when someone
# walks a camera along a table. Two thirds of the frame is travelled, so the
# thumbnail taken at the halfway point still shows the middle of the picture.
_PAN_HEADROOM = 1.25

# Every picture the service holds a file for: the primary's library and the partner's own.
_SERVED = (*ALL_PICTURES, *PARTNER_PICTURES)
_BY_ID = {picture.asset_id: picture for picture in _SERVED}
_VIDEOS = tuple(picture for picture in _SERVED if picture.is_video)
_PHOTOS = tuple(picture for picture in _SERVED if not picture.is_video)


def _person_payload(name: str) -> dict[str, Any]:
    """The household's cast as Immich returns a person: an id, a name, a face crop."""
    return {
        "id": f"person-{name.lower()}",
        "name": name,
        "birthDate": None,
        "thumbnailPath": f"/fake/people/{name.lower()}.jpg",
        "isHidden": False,
        "updatedAt": "2024-06-01T12:00:00.000Z",
    }


# The second account's own people: ids no other account holds, so a link has to be picked.
# One shares a name with a person the e2e registries hold (a suggestion), one does not.
PARTNER_PEOPLE = (
    ("partner-person-01", "Fixture Person 01", "1990-05-06"),
    ("partner-person-02", "Partner Only Friend", None),
    ("partner-person-03", "Robin", None),
)
PARTNER_USER = "Fixture Person 01"
PARTNER_USER_ID = "fake-partner-user"


def _partner_person_payload(person_id: str, name: str, born: str | None) -> dict[str, Any]:
    return {
        "id": person_id,
        "name": name,
        "birthDate": born,
        "thumbnailPath": f"/fake/people/{person_id}.jpg",
        "isHidden": False,
        "updatedAt": "2024-06-01T12:00:00.000Z",
    }


# The key under which a photo's edited render is served, beside its untouched original.
EDITED = "#edited"


def _photo_size(picture: Picture) -> tuple[int, int]:
    if picture.size is not None:
        return picture.size
    width, height = _PHOTO_SIZE
    return (height, width) if picture.portrait else (width, height)


def _asset_payload(picture: Picture, owner: str = "fake-user") -> dict[str, Any]:
    is_video = picture.is_video
    width, height = _VIDEO_SIZE if is_video else _photo_size(picture)
    return {
        "id": picture.asset_id,
        "deviceAssetId": f"fake-device-{picture.asset_id}",
        "ownerId": owner,
        "deviceId": "fake-device",
        "type": "VIDEO" if is_video else "IMAGE",
        "originalPath": f"/fake-library/{picture.filename}",
        "originalFileName": picture.filename,
        "originalMimeType": "video/mp4" if is_video else "image/jpeg",
        "thumbhash": None,
        "fileCreatedAt": picture.taken_at,
        "fileModifiedAt": picture.taken_at,
        "localDateTime": picture.taken_at,
        "updatedAt": picture.taken_at,
        "isFavorite": picture.is_favorite,
        "isEdited": picture.edited,
        "isArchived": False,
        "isTrashed": False,
        "duration": int(picture.seconds * 1000) if is_video else None,
        "width": width,
        "height": height,
        "exifInfo": {
            **_CAMERA_EXIF,
            "dateTimeOriginal": picture.taken_at,
            "fileSizeInByte": 400_000 if is_video else 20_000,
            "latitude": picture.place.latitude,
            "longitude": picture.place.longitude,
            "city": picture.place.city,
            "country": picture.place.country,
        },
        "people": [_person_payload(name) for name in picture.people],
        "faces": [],
        "checksum": f"fake-checksum-{picture.asset_id}",
        "livePhotoVideoId": picture.live_video_id,
        "smartInfo": {"objects": []},
    }


_PRIMARY_IDS = {picture.asset_id for picture in ALL_PICTURES}
TIMELINE_ASSETS = tuple(
    _asset_payload(picture) for picture in _VIDEOS if picture.asset_id in _PRIMARY_IDS
) + tuple(_asset_payload(picture) for picture in _PHOTOS if picture.asset_id in _PRIMARY_IDS)
# A Live Photo's companion clip: a video Immich links from its still and hides from the
# timeline and from search (v3 `visibility: hidden`), readable by id.
_LIVE = tuple(picture for picture in ALL_PICTURES if picture.live_video_id)


def _companion_payload(still: Picture) -> dict[str, Any]:
    # Taken at the still's own instant: the shutter sits in the middle of the clip.
    stamp = still.taken_at
    return _asset_payload(still) | {
        "id": still.live_video_id,
        "type": "VIDEO",
        "originalFileName": still.filename.replace(".HEIC", ".MOV"),
        "originalMimeType": "video/quicktime",
        "fileCreatedAt": stamp,
        "localDateTime": stamp,
        "duration": int(LIVE_CLIP_SECONDS * 1000),
        "width": _VIDEO_SIZE[0],
        "height": _VIDEO_SIZE[1],
        "livePhotoVideoId": None,
        "visibility": "hidden",
        "checksum": f"fake-checksum-{still.live_video_id}",
    }


COMPANION_ASSETS = tuple(_companion_payload(picture) for picture in _LIVE)

# What the partner key reads: its own pictures, which the primary key never sees.
PARTNER_ASSETS = tuple(_asset_payload(picture, PARTNER_USER_ID) for picture in PARTNER_PICTURES)

# One album, the lake week as a family would file it: every picture taken at the lake.
ALBUM_ID = "album-lake-week"
ALBUM_ASSETS = frozenset(
    asset["id"] for asset in TIMELINE_ASSETS if asset["exifInfo"]["city"] == "Annecy"
)
ALBUMS = (
    {
        "id": ALBUM_ID,
        "albumName": "The lake week",
        "assetCount": len(ALBUM_ASSETS),
        "startDate": "2024-06-21T00:00:00.000Z",
        "endDate": "2024-06-27T00:00:00.000Z",
    },
)


# Every place the library was photographed at, and the fixture home.
_PLACES = {picture.place for picture in (*ALL_PICTURES, *PARTNER_PICTURES)} | {HOME}
# About a kilometre: how near a point has to be for Immich to name the same place.
_PLACE_RADIUS_DEGREES = 0.01


def _reverse_geocode(query: dict[str, list[str]]) -> list[dict[str, Any]]:
    """Immich's answer: the place at those coordinates, or an empty list where it knows none."""
    try:
        lat, lon = float(query["lat"][-1]), float(query["lon"][-1])
    except (KeyError, ValueError):
        return []
    return [
        {"city": place.city, "state": None, "country": place.country}
        for place in _PLACES
        if abs(place.latitude - lat) <= _PLACE_RADIUS_DEGREES
        and abs(place.longitude - lon) <= _PLACE_RADIUS_DEGREES
    ][:1]


def _instant(stamp: str | None) -> datetime | None:
    return None if stamp is None else datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def _held(partner: bool) -> tuple[dict[str, Any], ...]:
    """The assets one key reads: each account holds only its own."""
    return PARTNER_ASSETS if partner else TIMELINE_ASSETS


def _month_of(taken_at: str) -> str:
    """The MONTH bucket an asset falls in, in the form Immich returns."""
    return f"{taken_at[:7]}-01T00:00:00.000Z"


def _assets_for_query(
    query: dict[str, list[str]], held: tuple[dict[str, Any], ...] = TIMELINE_ASSETS
) -> list[dict[str, Any]]:
    requested_type = query.get("type", [None])[0]
    requested_bucket = query.get("timeBucket", [None])[0]
    return [
        asset
        for asset in held
        if (requested_type is None or asset["type"] == requested_type)
        and (requested_bucket is None or _month_of(asset["fileCreatedAt"]) == requested_bucket)
    ]


def _buckets_for_query(
    query: dict[str, list[str]], held: tuple[dict[str, Any], ...] = TIMELINE_ASSETS
) -> list[dict[str, Any]]:
    """One MONTH bucket per month that holds a matching asset, newest first like Immich."""
    counts: dict[str, int] = {}
    for asset in _assets_for_query({k: v for k, v in query.items() if k != "timeBucket"}, held):
        month = _month_of(asset["fileCreatedAt"])
        counts[month] = counts.get(month, 0) + 1
    return [
        {"count": count, "timeBucket": month}
        for month, count in sorted(counts.items(), reverse=True)
    ]


def _assets_for_search(
    payload: dict[str, Any],
    held: tuple[dict[str, Any], ...] = TIMELINE_ASSETS,
    by_id: dict[str, Picture] | None = None,
) -> list[dict[str, Any]]:
    """The metadata search honours the type, the taken-at window and the faces.

    Several ``personIds`` intersect, which is what Immich answers and what the
    wizard's "Together" and a grouped condition's AND both count on.
    """
    requested_type = payload.get("type")
    # Immich compares instants, not strings: "16:32:00.000Z" is not after "16:32:00+00:00".
    taken_after = _instant(payload.get("takenAfter"))
    taken_before = _instant(payload.get("takenBefore"))
    wanted_people = set(payload.get("personIds") or ())
    wanted_albums = payload.get("albumIds") or ()
    return [
        asset
        for asset in held
        if (requested_type is None or asset["type"] == requested_type)
        and (taken_after is None or _instant(asset["fileCreatedAt"]) >= taken_after)
        and (taken_before is None or _instant(asset["fileCreatedAt"]) <= taken_before)
        and wanted_people <= {person["id"] for person in asset["people"]}
        and (not wanted_albums or (ALBUM_ID in wanted_albums and asset["id"] in ALBUM_ASSETS))
        and _reads((by_id or _BY_ID).get(asset["id"]), payload.get("ocr"))
    ]


def _faces_payload(picture: Picture) -> list[dict[str, Any]]:
    """Where Immich found each recognised person on a picture: one box apiece, side by side.

    Measured on the preview Immich ran detection over, which it names beside each box.
    """
    width, height = _VIDEO_SIZE if picture.is_video else _photo_size(picture)
    slot = width // max(1, len(picture.people))
    side = min(slot, height) // 3
    return [
        {
            "id": f"face-{picture.asset_id}-{index}",
            "person": _person_payload(name),
            "imageWidth": width,
            "imageHeight": height,
            "boundingBoxX1": index * slot + (slot - side) // 2,
            "boundingBoxY1": height // 4,
            "boundingBoxX2": index * slot + (slot + side) // 2,
            "boundingBoxY2": height // 4 + side,
            "sourceType": "machine-learning",
        }
        for index, name in enumerate(picture.people)
    ]


def _ocr_payload(picture: Picture) -> list[dict[str, Any]]:
    """Immich's OCR answer for a picture: one text box per printed line, top to bottom."""
    return [
        {
            "id": f"ocr-{picture.asset_id}-{line}",
            "assetId": picture.asset_id,
            "x1": 0.1,
            "y1": 0.1 + 0.05 * line,
            "x2": 0.9,
            "y2": 0.1 + 0.05 * line,
            "x3": 0.9,
            "y3": 0.14 + 0.05 * line,
            "x4": 0.1,
            "y4": 0.14 + 0.05 * line,
            "boxScore": 0.9,
            "textScore": 0.9,
            "text": text,
        }
        for line, text in enumerate(picture.ocr.splitlines())
    ]


def _reads(picture: Picture | None, words: str | None) -> bool:
    """Immich's `ocr` search: the asset's recognised text holds the words, case aside."""
    if not words:
        return True
    return picture is not None and words.casefold() in picture.ocr.casefold()


@dataclass(frozen=True, slots=True)
class RecordedUpload:
    """A multipart asset accepted by the fake service."""

    fields: dict[str, str]
    filename: str
    content_type: str
    data: bytes


@dataclass(slots=True)
class Wire:
    """What the service answers as, and every request it was sent, in order."""

    # The Immich major the service reports and holds requests to.
    major: int = 3
    # ("GET", "/api/assets/x/original"), ... in arrival order; query strings dropped.
    requests: list[tuple[str, str]] = dataclass_field(default_factory=list)


class FakeImmichServer:
    """Own a fixture-scoped HTTP server implementing the tested Immich surface."""

    api_key = "fake-immich-api-key"
    # A second account on the same server: its own roster and its own user.
    partner_api_key = "fake-immich-partner-key"

    def __init__(
        self,
        root: Path,
        httpd: ThreadingHTTPServer,
        thread: threading.Thread,
        source_video: Path,
        photo_paths: dict[str, Path],
        uploads: list[RecordedUpload],
        refused: list[str],
        wire: Wire | None = None,
        media: dict[str, Path] | None = None,
    ) -> None:
        self.root = root
        self.wire = wire or Wire()
        self._media = media if media is not None else {}
        # Requests answered 400 because the real Immich would refuse them (tests.immich_fakes).
        self.refused = refused
        self.source_video = source_video
        self.photo_paths = photo_paths
        self.uploads = uploads
        # What `start(media_of=...)` lends a second service; `start` fills them in.
        self._video_paths: dict[str, Path] = {}
        self._thumbnail_paths: dict[str, Path] = {}
        self._httpd = httpd
        self._thread = thread
        host, port = httpd.server_address[:2]
        if isinstance(host, bytes):
            host = host.decode("ascii")
        # A wildcard bind is an address to listen on, not one to call. Anyone
        # reading base_url wants something they can fetch, and a caller on this
        # machine can always fetch the loopback.
        self.base_url = f"http://{'127.0.0.1' if host == '0.0.0.0' else host}:{port}"  # noqa: S104

    @classmethod
    def start(
        cls,
        root: Path,
        *,
        upload_commit_delay: float = 0.0,
        host: str = "127.0.0.1",
        port: int = 0,
        media_of: FakeImmichServer | None = None,
        held: tuple[Picture, ...] = (),
    ) -> Self:
        """Start the service, by default on an operating-system-selected localhost port.

        `host` and `port` exist for the setup matrix, which has to serve this
        library to a NAS and a cluster over the LAN. Every asset URL the service
        hands out is relative, so binding elsewhere needs no other change.

        `media_of` serves another running service's rendered media instead of
        rendering it again (about 14 s of FFmpeg): a second server with the same
        library and none of the first one's uploads, tags or refusals.

        `held` adds pictures the shared library leaves out (`fake_library.HELD_PICTURES`):
        this service alone serves them, drawn into its own media folder.
        """
        root.mkdir(parents=True, exist_ok=True)
        if media_of is not None:
            video_paths, photo_paths = media_of._video_paths, media_of.photo_paths
            thumbnail_paths = media_of._thumbnail_paths
        else:
            media_dir = root / "media"
            media_dir.mkdir(exist_ok=True)
            video_paths = _generate_videos(media_dir) | _generate_live_clips(media_dir)
            photo_paths = _generate_photos(media_dir)
            thumbnail_paths = _generate_thumbnails(media_dir, video_paths | photo_paths)
        if held:
            held_dir = root / "held-media"
            held_dir.mkdir(exist_ok=True)
            drawn = _draw_held(held_dir, held)
            photo_paths = photo_paths | drawn
            thumbnail_paths = thumbnail_paths | _generate_thumbnails(held_dir, drawn)
        media = video_paths | photo_paths
        uploads: list[RecordedUpload] = []
        refused: list[str] = []
        wire = Wire()
        httpd = ThreadingHTTPServer(
            (host, port),
            _handler_type(
                media, thumbnail_paths, uploads, upload_commit_delay, refused, wire, held
            ),
        )
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        server = cls(
            root,
            httpd,
            thread,
            video_paths[_VIDEOS[0].asset_id],
            photo_paths,
            uploads,
            refused,
            wire,
            media,
        )
        server._video_paths = video_paths
        server._thumbnail_paths = thumbnail_paths
        return server

    @contextlib.contextmanager
    def answering_as(self, major: int) -> Iterator[None]:
        """Report Immich `major` (2 or 3) and hold requests to that release's contract."""
        before, self.wire.major = self.wire.major, major
        try:
            yield
        finally:
            self.wire.major = before

    def original(self, asset_id: str) -> Path:
        """The file served as this asset's original."""
        return self._media[asset_id]

    @contextlib.contextmanager
    def serving(self, originals: dict[str, Path]) -> Iterator[None]:
        """Serve these files as the originals of these asset ids until the block ends."""
        before = {asset_id: self._media[asset_id] for asset_id in originals}
        self._media.update(originals)
        try:
            yield
        finally:
            self._media.update(before)

    @property
    def listening_host(self) -> str:
        """The address the socket is bound to, which is not always one to call."""
        host = self._httpd.server_address[0]
        return host.decode("ascii") if isinstance(host, bytes) else str(host)

    def close(self) -> None:
        """Stop the service and release its listening socket."""
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)


def _ffmpeg(*args: str) -> None:
    subprocess.run(  # noqa: S603
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _generate_live_clips(media_dir: Path) -> dict[str, Path]:
    """Each Live Photo's companion clip, made from its own still.

    "moving": a second copy of the picture slides across it, so something moves against a
    still background, the kind of motion worth playing. "steady": the picture alone, where
    nothing moves. "burst": cuts of one continuous recording of that sliding picture (its
    sound included), each clip starting where its shutter sits in the recording, so
    neighbouring clips share the same frames and sound where they overlap.
    """
    clips: dict[str, Path] = {}
    bursts: dict[Path, Path] = {}
    for picture in _LIVE:
        clip = media_dir / f"{picture.live_video_id}.mp4"
        if picture.motion == "burst":
            if picture.source not in bursts:
                recording = media_dir / f"burst-{picture.source.stem}.mp4"
                takes = sum(1 for p in _LIVE if p.motion == "burst" and p.source == picture.source)
                _live_recording(
                    picture.source, recording, LIVE_CLIP_SECONDS + takes * BURST_STEP_SECONDS
                )
                bursts[picture.source] = recording
            _ffmpeg(
                "-ss", f"{picture.burst_offset:.3f}", "-i", str(bursts[picture.source]),
                "-t", str(LIVE_CLIP_SECONDS), *_LIVE_ENCODE, str(clip),
            )  # fmt: skip
        else:
            _live_recording(
                picture.source, clip, LIVE_CLIP_SECONDS, moving=picture.motion == "moving"
            )
        clips[picture.live_video_id] = clip
    return clips


_LIVE_ENCODE = (
    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
    "-color_range", "tv", "-color_primaries", "bt709", "-color_trc", "bt709",
    "-colorspace", "bt709", "-r", "30", "-c:a", "aac", "-movflags", "+faststart",
)  # fmt: skip


# How fast the two halves of a moving Live clip slide past each other, in pixels a second.
_LIVE_SLIDE = 240


def _live_recording(source: Path, path: Path, seconds: float, *, moving: bool = True) -> None:
    """`seconds` of the picture at 1920x1080.

    Moving, its top half slides left while its bottom half slides right: motion no camera
    pan explains, which is what the editor's motion measure looks for. Steady, it holds.
    """
    width, height = _VIDEO_SIZE
    wide = width + round(_LIVE_SLIDE * seconds)
    prepared = (
        f"[0:v]scale={wide}:{height}:force_original_aspect_ratio=increase,crop={wide}:{height},"
        "scale=in_range=full:out_range=tv,format=yuv420p,split[a][b]"
    )
    graph = (
        f"{prepared};[a]crop={width}:{height // 2}:x='t*{_LIVE_SLIDE}':y=0[top];"
        f"[b]crop={width}:{height // 2}:x='{wide - width}-t*{_LIVE_SLIDE}':y={height // 2}[bottom];"
        "[top][bottom]vstack[v]"
        if moving
        else f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},scale=in_range=full:out_range=tv,format=yuv420p[v]"
    )
    _ffmpeg(
        "-loop", "1", "-framerate", "30", "-i", str(source),
        "-f", "lavfi", "-i", f"anoisesrc=color=pink:seed=7:amplitude=0.05:duration={seconds}",
        "-filter_complex", graph, "-map", "[v]", "-map", "1:a:0", "-t", str(seconds),
        *_LIVE_ENCODE, str(path),
    )  # fmt: skip


def _generate_videos(media_dir: Path) -> dict[str, Path]:
    """Pan across each source photograph for four seconds, over a silent audio track."""
    width, height = _VIDEO_SIZE
    stage_w, stage_h = round(width * _PAN_HEADROOM), round(height * _PAN_HEADROOM)
    videos: dict[str, Path] = {}
    for picture in _VIDEOS:
        video_path = media_dir / f"{picture.asset_id}.mp4"
        _ffmpeg(
            "-loop",
            "1",
            "-framerate",
            "30",
            "-i",
            str(picture.source),
            "-f",
            "lavfi",
            # WHY silent: a phone clip carries an audio stream, and the render keeps it under the
            # music; a test tone here was the soundtrack of every film cut from this library.
            # One clip (`voiced`) keeps a quiet hum, so a film can be heard keeping or muting it.
            "-i",
            (
                f"sine=frequency=220:sample_rate=48000:duration={picture.seconds},"
                "volume=-18dB,aformat=channel_layouts=stereo"
                if picture.voiced
                else f"anullsrc=channel_layout=stereo:sample_rate=48000:duration={picture.seconds}"
            ),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-t",
            str(picture.seconds),
            "-vf",
            (
                f"scale={stage_w}:{stage_h}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height}:"
                f"x='(in_w-out_w)*t/{picture.seconds}',"
                # WHY: a JPEG decodes full-range, and libx264 would then tag the
                # clip yuvj420p -- which the production probe reads as unknown.
                "scale=in_range=full:out_range=tv,format=yuv420p"
            ),
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-color_range",
            "tv",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
            "-colorspace",
            "bt709",
            "-x264-params",
            "colorprim=bt709:transfer=bt709:colormatrix=bt709",
            "-c:a",
            "aac",
            "-shortest",
            "-movflags",
            "+faststart",
            str(video_path),
        )
        videos[picture.asset_id] = video_path
    return videos


def _generate_photos(media_dir: Path) -> dict[str, Path]:
    """Serve each source photograph at the size its asset record advertises.

    A photo edited in Immich's editor also gets its edited render: the same picture in black
    and white, which Immich serves when asked for `edited=true`.
    """
    photos: dict[str, Path] = {}
    for picture in _PHOTOS:
        _write_photo(picture, media_dir / f"{picture.asset_id}.jpg", photos, picture.asset_id)
        if picture.hdr:
            _add_gain_map(media_dir / f"{picture.asset_id}.jpg")
        if picture.edited:
            edited = media_dir / f"{picture.asset_id}.edited.jpg"
            _write_photo(picture, edited, photos, picture.asset_id + EDITED, ",hue=s=0")
    return photos


def _draw_held(media_dir: Path, held: tuple[Picture, ...]) -> dict[str, Path]:
    """Draw each held picture at the size its record advertises; nobody is in any of them.

    One with recognised text is a printed form photographed on a table: grey lines on a
    white page. Any other is a phone screenshot: message bubbles on a light screen.
    """
    drawn: dict[str, Path] = {}
    for picture in held:
        width, height = _photo_size(picture)
        if picture.ocr:
            page_w, page_h = width * 2 // 5, height * 4 // 5
            left, top = (width - page_w) // 2, (height - page_h) // 2
            lines = ",".join(
                f"drawbox=x={left + page_w // 10}:y={top + page_h // 8 + row * page_h // 12}:"
                f"w={page_w * (5 + row % 3) // 10}:h={page_h // 40}:color=0x707070:t=fill"
                for row in range(9)
            )
            scene = (
                f"color=c=0x6B4A2E:s={width}x{height},"
                f"drawbox=x={left}:y={top}:w={page_w}:h={page_h}:color=white:t=fill,{lines}"
            )
        else:
            bubbles = ",".join(
                f"drawbox=x={width // 20 if row % 2 else width // 3}:"
                f"y={height // 10 + row * height // 9}:w={width * 3 // 5}:h={height // 14}:"
                f"color={'0xE5E5EA' if row % 2 else '0x0A84FF'}:t=fill"
                for row in range(8)
            )
            scene = f"color=c=0xF2F2F7:s={width}x{height},{bubbles}"
        path = media_dir / f"{picture.asset_id}.jpg"
        _ffmpeg("-f", "lavfi", "-i", scene, "-frames:v", "1", "-q:v", "2", str(path))
        drawn[picture.asset_id] = path
    return drawn


def _write_photo(
    picture: Picture, photo_path: Path, photos: dict[str, Path], key: str, edit: str = ""
) -> None:
    width, height = _photo_size(picture)
    _ffmpeg(
        "-i",
        str(picture.source),
        "-vf",
        (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}{edit}"
        ),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        "-update",
        "1",
        str(photo_path),
    )
    photos[key] = photo_path


def _add_gain_map(photo: Path) -> None:
    """Make a photo an Ultra HDR JPEG: the picture tagged `hdrgm`, then its gain map.

    The gain map brightens the picture's own highlights, so the HDR rendition is the same
    picture with more headroom, as a phone's is.
    """
    import io

    from PIL import Image

    with Image.open(photo) as image:
        primary = io.BytesIO()
        image.save(primary, "JPEG", quality=92, comment=b"hdrgm:Version=1.0")
        gain = io.BytesIO()
        image.convert("L").resize((image.width // 4, image.height // 4)).save(gain, "JPEG")
    photo.write_bytes(primary.getvalue() + gain.getvalue())


def _generate_thumbnails(media_dir: Path, media: dict[str, Path]) -> dict[str, Path]:
    """Render each asset its own preview, the way Immich serves one per asset.

    One shared thumbnail made every asset a perceptual duplicate of every
    other, and Phase 1 clustering collapsed the whole pool into one clip.
    """
    thumbnail_dir = media_dir / "thumbnails"
    # The setup matrix serves one library twice into the same output directory,
    # once per lane invocation, and every render below overwrites what it finds.
    thumbnail_dir.mkdir(exist_ok=True)
    thumbnails: dict[str, Path] = {}
    for asset_id, source in media.items():
        thumbnail_path = thumbnail_dir / f"{asset_id.replace(EDITED, '.edited')}.jpg"
        seconds = _BY_ID[asset_id].seconds if asset_id in _BY_ID else _VIDEO_DURATION
        seek = ["-ss", str(seconds / 2)] if source.suffix == ".mp4" else []
        _ffmpeg(
            *seek,
            "-i",
            str(source),
            "-frames:v",
            "1",
            "-vf",
            "scale=1440:-2",
            "-q:v",
            "3",
            "-update",
            "1",
            str(thumbnail_path),
        )
        thumbnails[asset_id] = thumbnail_path
    return thumbnails


def _handler_type(
    media: dict[str, Path],
    thumbnails: dict[str, Path],
    uploads: list[RecordedUpload],
    upload_commit_delay: float,
    refused: list[str],
    wire: Wire | None = None,
    held: tuple[Picture, ...] = (),
) -> type[BaseHTTPRequestHandler]:
    upload_lock = threading.Lock()
    # The primary account's pictures on this service: the library and any held ones.
    held_assets = tuple(_asset_payload(picture) for picture in held)
    by_id = _BY_ID | {picture.asset_id: picture for picture in held}

    def assets_of(partner: bool) -> tuple[dict[str, Any], ...]:
        return _held(partner) if partner else _held(partner) + held_assets

    wire = wire or Wire()
    # Tags created on this service, by value, and the assets each one holds.
    tags: dict[str, dict[str, Any]] = {}
    tagged: dict[str, set[str]] = {}

    def uploaded_asset(asset_id: str) -> dict[str, Any] | None:
        """An uploaded film as Immich serves it once read: its name, dates and tags."""
        index = asset_id.removeprefix("uploaded-")
        with upload_lock:
            if not index.isdigit() or not 0 < int(index) <= len(uploads):
                return None
            upload = uploads[int(index) - 1]
        created = upload.fields.get("fileCreatedAt", "")
        return {
            "id": asset_id,
            "type": "VIDEO",
            "originalFileName": upload.filename,
            "fileCreatedAt": created,
            "fileModifiedAt": upload.fields.get("fileModifiedAt", created),
            # Immich's metadata job has read the file: what a fresh upload waits for.
            "exifInfo": {"modifyDate": upload.fields.get("fileModifiedAt", created)},
            "tags": [tag for tag in tags.values() if asset_id in tagged[tag["id"]]],
        }

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def parse_request(self) -> bool:
            parsed = super().parse_request()
            if parsed:
                wire.requests.append((self.command, urlsplit(self.path).path))
            return parsed

        def do_GET(self) -> None:  # noqa: N802
            key = self.headers.get("x-api-key")
            if key not in (FakeImmichServer.api_key, FakeImmichServer.partner_api_key):
                self._send_json(401, {"message": "invalid API key"})
                return
            partner = key == FakeImmichServer.partner_api_key
            request_url = urlsplit(self.path)
            path = request_url.path
            query = parse_qs(request_url.query)
            if self._refused(path, query, None):
                return
            if path == "/api/server/version":
                self._send_json(200, {"major": wire.major, "minor": 1, "patch": 0})
                return
            if path == "/api/api-keys/me":
                self._send_json(200, {"permissions": ["all"]})
                return
            if path == "/api/users/me":
                self._send_json(
                    200,
                    {
                        "id": PARTNER_USER_ID if partner else "fake-user",
                        "email": "fake@example.test",
                        "name": PARTNER_USER if partner else "Fake Immich User",
                        "isAdmin": True,
                    },
                )
                return
            if path == "/api/map/reverse-geocode":
                self._send_json(200, _reverse_geocode(query))
                return
            if path == "/api/tags":
                self._send_json(200, list(tags.values()))
                return
            if path == "/api/albums":
                holding = query.get("assetId", [None])[0]
                albums = [a for a in ALBUMS if holding is None or holding in ALBUM_ASSETS]
                self._send_json(200, albums)
                return
            if path == "/api/people":
                people = (
                    [_partner_person_payload(*person) for person in PARTNER_PEOPLE]
                    if partner
                    else [_person_payload(name) for name in CAST]
                )
                self._send_json(200, {"people": people, "total": len(people), "hidden": 0})
                return
            if path.startswith("/api/people/") and path.endswith("/statistics"):
                person_id = path.split("/")[-2]
                if partner:
                    self._send_json(200, {"assets": 120 if person_id.endswith("01") else 30})
                    return
                count = sum(
                    person_id == f"person-{name.lower()}"
                    for picture in ALL_PICTURES
                    for name in picture.people
                )
                self._send_json(200, {"assets": count})
                return
            if path == "/api/stacks":
                # The fixture library stacks nothing.
                self._send_json(200, [])
                return
            if path == "/api/faces":
                # Where each recognised person sits; the asset record names them without boxes.
                found = by_id.get(query.get("id", [""])[-1])
                self._send_json(200, _faces_payload(found) if found else [])
                return
            if path == "/api/timeline/buckets":
                self._send_json(200, _buckets_for_query(query, assets_of(partner)))
                return
            if path == "/api/timeline/bucket":
                self._send_json(200, _assets_for_query(query, assets_of(partner)))
                return
            parts = path.removeprefix("/api/assets/").split("/")
            if path.startswith("/api/assets/") and len(parts) == 1:
                # One asset by id, as Immich serves it: a revision's swap fetches its sibling so.
                found = next(
                    (a for a in (*assets_of(partner), *COMPANION_ASSETS) if a["id"] == parts[0]),
                    None,
                )
                found = found or uploaded_asset(parts[0])
                if found is not None:
                    self._send_json(200, found)
                    return
            if len(parts) == 2 and parts[1] == "ocr" and parts[0] in by_id:
                # Immich answers 404 for an asset its OCR job read no text on.
                if by_id[parts[0]].ocr:
                    self._send_json(200, _ocr_payload(by_id[parts[0]]))
                else:
                    self._send_json(404, {"message": "Asset OCR not found"})
                return
            if query.get("edited") == ["true"] and parts[0] + EDITED in media:
                # Immich's editor render, asked for by name; any other asset has none to give.
                parts = [parts[0] + EDITED, parts[1]]
            if len(parts) == 2 and parts[0] in media and parts[1] == "original":
                content_type = "video/mp4" if media[parts[0]].suffix == ".mp4" else "image/jpeg"
                self._send_file(media[parts[0]], content_type)
                return
            if len(parts) == 2 and parts[0] in thumbnails and parts[1] == "thumbnail":
                self._send_file(thumbnails[parts[0]], "image/jpeg")
                return
            person = path.removeprefix("/api/people/").split("/")
            if path.startswith("/api/people/") and len(person) == 1:
                # One person by id: the account that holds them answers, the other refuses.
                held = {p[0]: p for p in PARTNER_PEOPLE} if partner else {}
                if not partner:
                    held = {f"person-{name.lower()}": None for name in CAST}
                if person[0] not in held:
                    self._send_json(404, {"message": "person not found"})
                    return
                found = held[person[0]]
                self._send_json(
                    200,
                    _partner_person_payload(*found)
                    if found
                    else _person_payload(person[0].removeprefix("person-").title()),
                )
                return
            if (
                len(person) == 2
                and person[1] == "thumbnail"
                and not path.startswith("/api/assets/")
            ):
                # Every person gets the same CC0 face stand-in: the People page
                # only needs a picture that decodes, not a likeness.
                self._send_file(next(iter(thumbnails.values())), "image/jpeg")
                return
            if (
                len(parts) == 3
                and parts[0] in media
                and media[parts[0]].suffix == ".mp4"
                and parts[1:] == ["video", "playback"]
            ):
                self._send_file(media[parts[0]], "video/mp4")
                return
            if path.startswith("/api/assets/") and parts[0] not in by_id:
                # What Immich answers for an id this key cannot read, whether or not it exists.
                self._send_json(400, {"message": "Not found or no asset.read access"})
                return
            self._unexpected()

        def do_POST(self) -> None:  # noqa: N802
            key = self.headers.get("x-api-key")
            if key not in (FakeImmichServer.api_key, FakeImmichServer.partner_api_key):
                self._send_json(401, {"message": "invalid API key"})
                return
            partner = key == FakeImmichServer.partner_api_key
            path = urlsplit(self.path).path
            if path == "/api/search/metadata":
                payload = self._read_json()
                if self._refused(path, {}, payload):
                    return
                items = _assets_for_search(payload, assets_of(partner), by_id)
                if wanted_tags := payload.get("tagIds"):
                    items = self._tagged(items, wanted_tags)
                self._send_json(
                    200,
                    {
                        "assets": {
                            "total": len(items),
                            "count": len(items),
                            "items": items,
                            "nextPage": None,
                        }
                    },
                )
                return
            if path == "/api/search/statistics":
                # Same filters as the metadata search, answered as Immich does: a count only.
                payload = self._read_json()
                if self._refused(path, {}, payload):
                    return
                self._send_json(
                    200, {"total": len(_assets_for_search(payload, assets_of(partner), by_id))}
                )
                return
            if path == "/api/assets" and not partner:
                try:
                    upload = self._read_multipart()
                except ValueError as error:
                    self._send_json(400, {"message": str(error)})
                    return
                form = {**upload.fields, "assetData": upload.filename}
                if self._refused(path, {}, None, form=form):
                    return
                with upload_lock:
                    uploads.append(upload)
                    if upload_commit_delay:
                        time.sleep(upload_commit_delay)
                    asset_id = f"uploaded-{len(uploads)}"
                self._send_json(
                    201,
                    {"id": asset_id, "status": "created"},
                )
                return
            self._unexpected()

        def do_PUT(self) -> None:  # noqa: N802
            if self.headers.get("x-api-key") != FakeImmichServer.api_key:
                self._send_json(401, {"message": "invalid API key"})
                return
            path = urlsplit(self.path).path
            payload = self._read_json()
            if self._refused(path, {}, payload):
                return
            if path == "/api/tags":
                # Upsert by value, answered with the tags as Immich returns them.
                for value in payload.get("tags") or ():
                    if value not in tags:
                        tag_id = f"tag-{len(tags) + 1}"
                        tags[value] = {
                            "id": tag_id,
                            "name": value.rsplit("/", 1)[-1],
                            "value": value,
                            "createdAt": "2024-01-01T00:00:00.000Z",
                            "updatedAt": "2024-01-01T00:00:00.000Z",
                        }
                        tagged[tag_id] = set()
                self._send_json(200, [tags[value] for value in payload.get("tags") or ()])
                return
            tag_id = path.removeprefix("/api/tags/").removesuffix("/assets")
            if path.endswith("/assets") and tag_id in tagged:
                ids = list(payload.get("ids") or ())
                tagged[tag_id].update(ids)
                self._send_json(200, [{"id": asset_id, "success": True} for asset_id in ids])
                return
            self._unexpected()

        def do_PATCH(self) -> None:  # noqa: N802
            self._unexpected()

        def do_DELETE(self) -> None:  # noqa: N802
            self._unexpected()

        def _tagged(
            self, items: list[dict[str, Any]], wanted_tags: list[str]
        ) -> list[dict[str, Any]]:
            """What Immich answers for `tagIds`: only the assets carrying every tag, films
            this service took as uploads included. Ignoring the filter would call every
            picture in the library one of the app's own films once anything was tagged."""
            holding = set.intersection(*(tagged.get(tag_id, set()) for tag_id in wanted_tags))
            films = (uploaded_asset(asset_id) for asset_id in sorted(holding))
            return [asset for asset in items if asset["id"] in holding] + [
                film for film in films if film is not None
            ]

        def _refused(
            self,
            path: str,
            query: dict[str, list[str]],
            body: Any,
            form: dict[str, str] | None = None,
        ) -> bool:
            """Answer 400 to what the real Immich would refuse, and remember it.

            The fixture's ids are readable names, so only the id format goes unchecked.
            """
            flat = {name: values[-1] for name, values in query.items()}
            # The contract of the major the server reports is the one it holds requests to.
            releases = V2 if wire.major == 2 else V3
            problems = request_problems(
                self.command, path, flat, body, uuid_ids=False, releases=releases
            )
            if not problems:
                return False
            refused.extend(f"{self.command} {path}: {problem}" for problem in problems)
            self._send_json(400, {"message": problems, "error": "Bad Request", "statusCode": 400})
            return True

        def _read_json(self) -> dict[str, Any]:
            content_length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(content_length)
            payload = json.loads(body) if body else {}
            return payload if isinstance(payload, dict) else {}

        def _read_multipart(self) -> RecordedUpload:
            content_type = self.headers.get("Content-Type", "")
            if not content_type.startswith("multipart/form-data;"):
                raise ValueError("expected multipart/form-data")
            content_length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(content_length)
            message = BytesParser(policy=policy.default).parsebytes(
                f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + body
            )
            fields: dict[str, str] = {}
            upload: RecordedUpload | None = None
            for part in message.iter_parts():
                name = part.get_param("name", header="content-disposition")
                if not isinstance(name, str):
                    continue
                value = part.get_payload(decode=True)
                if not isinstance(value, bytes):
                    raise ValueError("multipart part has no byte payload")
                filename = part.get_filename()
                if name == "assetData" and filename:
                    upload = RecordedUpload(
                        fields=fields,
                        filename=filename,
                        content_type=part.get_content_type(),
                        data=value,
                    )
                elif filename is None:
                    fields[name] = value.decode("utf-8")
            if upload is None:
                raise ValueError("assetData is required")
            for field in ("deviceAssetId", "deviceId"):
                if field in fields:
                    raise ValueError(f"v3 upload rejects {field}")
            return upload

        def _unexpected(self) -> None:
            self._send_json(
                500,
                {
                    "error": "unexpected fake Immich request",
                    "method": self.command,
                    "path": self.path,
                },
            )

        def _send_json(self, status: int, payload: Any) -> None:
            body = json.dumps(payload, separators=(",", ":")).encode()
            self._send_bytes(status, body, "application/json")

        def _send_file(self, path: Path, content_type: str) -> None:
            self._send_bytes(200, path.read_bytes(), content_type)

        def _send_bytes(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.close_connection = True

        def log_message(self, _format: str, *args: object) -> None:
            return

    return Handler
