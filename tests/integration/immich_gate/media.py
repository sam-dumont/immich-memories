"""The files the gate uploads into a real Immich: the CC0 fixture month and a paging album.

Two sets, both public and synthetic, never anyone's library:

* The June 2024 household of ``tests/e2e/fake_library.py``: every still becomes a
  1920x1280 JPEG carrying a camera and its capture time in EXIF (selection drops
  a still that names no camera), every video scene a 1080p pan across its
  photograph with a tone under it, stamped with the same time.
* Two dated sets for the memory types that need a second year on the same days: the
  busiest June day again a year earlier (``ECHO_DAY``, for on this day) and a set on
  25 December in two years (``CHRISTMAS_YEARS``, for the named holiday). Their stills are
  copies of fixture stills with other capture times, so no extra artwork ships.
* ``BULK_COUNT`` tiny, distinct JPEGs in March 2019 for the album that has to
  page: Immich answers a metadata search at most 1000 items at a time.

Building takes about fifteen seconds of FFmpeg, so the result is kept under ``root`` with a
fingerprint of its inputs and reused until those change (CI caches the folder).
"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from PIL import Image, ImageOps

from tests.e2e.fake_library import ALL_PICTURES, Picture

VIDEO_SIZE = (1920, 1080)
PHOTO_SIZE = (1920, 1280)
CAMERA = ("FakeCam", "Hermetic One")

# One more than a full page of Immich's metadata search, plus a margin, so the
# album and its year can only be read whole by asking for a second page.
BULK_COUNT = 1010
BULK_START = datetime(2019, 3, 1, 9, 0, tzinfo=UTC)
BULK_ALBUM = "Gate paging album"

# The busiest day of the fixture month, repeated a year earlier.
ECHO_DAY = (2024, 6, 15)
ECHO_YEAR = 2023
ECHO_COUNT = 5
CHRISTMAS_YEARS = (2023, 2024)
CHRISTMAS_COUNT = 4

_EXIF_MAKE = 0x010F
_EXIF_MODEL = 0x0110
_EXIF_IFD = 0x8769
_DATETIME_ORIGINAL = 0x9003
_OFFSET_TIME_ORIGINAL = 0x9011
_PAN_HEADROOM = 1.25


@dataclass(frozen=True, slots=True)
class GateFile:
    """One file to upload, and when its content happened."""

    path: Path
    taken_at: datetime
    picture: Picture | None = None


def taken_at(picture: Picture) -> datetime:
    return datetime.fromisoformat(picture.taken_at.replace("Z", "+00:00"))


def _fingerprint() -> str:
    digest = hashlib.sha256(Path(__file__).read_bytes())
    for picture in ALL_PICTURES:
        digest.update(f"{picture.asset_id}|{picture.filename}|{picture.taken_at}".encode())
        digest.update(picture.source.read_bytes())
    return digest.hexdigest()


def _exif(moment: datetime, *, camera: bool) -> Image.Exif:
    exif = Image.Exif()
    if camera:
        exif[_EXIF_MAKE], exif[_EXIF_MODEL] = CAMERA
    details = exif.get_ifd(_EXIF_IFD)
    details[_DATETIME_ORIGINAL] = moment.strftime("%Y:%m:%d %H:%M:%S")
    details[_OFFSET_TIME_ORIGINAL] = "+00:00"
    return exif


def _write_photo(
    picture: Picture, target: Path, moment: datetime | None = None, variant: int = 0
) -> None:
    with Image.open(picture.source) as source:
        image = source.convert("RGB")
    if variant:
        # A re-dated copy of the same pixels is one picture in two files, and the app folds
        # it away; a mirrored crop from another corner reads as a different shot.
        width, height = image.size
        left = 0 if variant % 2 else width // 4
        image = ImageOps.mirror(image.crop((left, height // 8, left + width * 3 // 4, height)))
    fitted = ImageOps.fit(image, PHOTO_SIZE)
    fitted.save(target, "JPEG", quality=85, exif=_exif(moment or taken_at(picture), camera=True))


def _write_video(picture: Picture, target: Path, tone: int) -> None:
    width, height = VIDEO_SIZE
    stage_w, stage_h = round(width * _PAN_HEADROOM), round(height * _PAN_HEADROOM)
    seconds = str(picture.seconds)
    subprocess.run(  # noqa: S603 -- fixed argv, fixture paths only
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-loop",
            "1",
            "-framerate",
            "30",
            "-i",
            str(picture.source),
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={tone}:sample_rate=48000:duration={seconds}",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-t",
            seconds,
            "-vf",
            (
                f"scale={stage_w}:{stage_h}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height}:x='(in_w-out_w)*t/{seconds}',"
                "scale=in_range=full:out_range=tv,format=yuv420p"
            ),
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-color_range",
            "tv",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
            "-colorspace",
            "bt709",
            "-c:a",
            "aac",
            "-shortest",
            "-metadata",
            f"creation_time={picture.taken_at}",
            "-movflags",
            "+faststart",
            str(target),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def _write_bulk(index: int, target: Path) -> None:
    # WHY distinct pixels: Immich refuses a second upload of the same checksum,
    # so each of the thousand needs content of its own.
    colour = (index % 256, (index // 256) * 40 % 256, (index * 7) % 256)
    Image.new("RGB", (32, 32), colour).save(
        target, "JPEG", quality=95, exif=_exif(bulk_taken_at(index), camera=False)
    )


def bulk_taken_at(index: int) -> datetime:
    return BULK_START + timedelta(minutes=index)


def library_files(root: Path) -> list[GateFile]:
    return [
        GateFile(root / "library" / picture.filename, taken_at(picture), picture)
        for picture in ALL_PICTURES
    ]


def _dated_sources() -> tuple[list[Picture], list[Picture]]:
    """The fixture stills the echo day and the Christmas set borrow their pictures from."""
    stills = [picture for picture in ALL_PICTURES if not picture.is_video]
    day = date(*ECHO_DAY)
    echo = [p for p in stills if taken_at(p).date() == day][:ECHO_COUNT]
    other = [p for p in stills if taken_at(p).date() != day]
    return echo, other[:CHRISTMAS_COUNT]


def dated_files(root: Path) -> list[GateFile]:
    """The echo day a year earlier, and 25 December in each of ``CHRISTMAS_YEARS``."""
    echo, christmas = _dated_sources()
    files = [
        GateFile(
            root / "dated" / f"GATE_ECHO_{index:02d}.jpg",
            taken_at(picture).replace(year=ECHO_YEAR),
            picture,
        )
        for index, picture in enumerate(echo)
    ]
    for year in CHRISTMAS_YEARS:
        files += [
            GateFile(
                root / "dated" / f"GATE_XMAS_{year}_{index:02d}.jpg",
                datetime(year, 12, 25, 10 + index, 0, tzinfo=UTC),
                picture,
            )
            for index, picture in enumerate(christmas)
        ]
    return files


def _write_dated(root: Path) -> None:
    echo, christmas = _dated_sources()
    sources = [(picture, 1) for picture in echo]
    for variant, _year in enumerate(CHRISTMAS_YEARS, start=1):
        sources += [(picture, variant) for picture in christmas]
    for gate_file, (picture, variant) in zip(dated_files(root), sources, strict=True):
        _write_photo(picture, gate_file.path, gate_file.taken_at, variant)


def bulk_files(root: Path) -> list[GateFile]:
    return [
        GateFile(root / "bulk" / f"GATE_BULK_{index:04d}.jpg", bulk_taken_at(index))
        for index in range(BULK_COUNT)
    ]


def build(root: Path) -> None:
    """Write every gate file under ``root`` unless an identical build is already there."""
    stamp = root / "fingerprint"
    fingerprint = _fingerprint()
    if stamp.exists() and stamp.read_text() == fingerprint:
        return
    (root / "library").mkdir(parents=True, exist_ok=True)
    (root / "bulk").mkdir(parents=True, exist_ok=True)
    (root / "dated").mkdir(parents=True, exist_ok=True)
    _write_dated(root)
    videos = 0
    for gate_file in library_files(root):
        picture = gate_file.picture
        assert picture is not None
        if picture.is_video:
            _write_video(picture, gate_file.path, tone=440 + videos * 110)
            videos += 1
        else:
            _write_photo(picture, gate_file.path)
    for index, gate_file in enumerate(bulk_files(root)):
        _write_bulk(index, gate_file.path)
    stamp.write_text(fingerprint)
