#!/usr/bin/env python3
"""Build the demo library from real Wikimedia Commons files.

The fixture library behind the screenshots, the demo film and the e2e tests is
real photographs and clips from Commons, each served with the place and time it
was really taken. ``tests/e2e/fixtures/library/sources.json`` lists the files by
their Commons title and says how each one is used; this script resolves them:

- reads each file's own licence and refuses anything but CC0 and CC BY;
- downloads the picture at its tier size (``film`` pictures can reach a cut,
  ``pool`` pictures only ever get culled) and strips its metadata;
- trims and re-encodes clips to 720p H.264;
- records the GPS and capture time from the file's metadata, shifted by its
  set's whole-day offset, and names the place with Nominatim; the one indoor
  series that stands for the household's home is placed there instead;
- finds the faces in pictures that show the household and pins each one to a
  cast member, left to right;
- writes ``library.json`` (what the fake Immich serves) and ``CREDITS.md``.

A location is never made up outdoors: a picture carries the GPS of its file or
none. Indoors, one series from one shoot may carry the household's home.
Run it through ``make fixture-library``; it talks to Commons and Nominatim, so
it is a maintainer tool, never part of a test run. Answers are cached under
``--cache`` so a rebuild after a curation change only fetches what is new.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from html import unescape
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LIBRARY_DIR = ROOT / "tests" / "e2e" / "fixtures" / "library"
API = "https://commons.wikimedia.org/w/api.php"
NOMINATIM = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = "immich-memories-fixture-library/1.0 (https://github.com/sam-dumont/immich-memories)"

# The licences a fixture file may carry. CC0 is preferred; CC BY only asks for the
# credit line CREDITS.md already gives. Share-alike, non-commercial and no-derivatives
# licences would bind the repository, so they are refused.
ACCEPTED_LICENCES = frozenset({"CC0", "CC BY 2.0", "CC BY 3.0", "CC BY 4.0"})

# Commons only serves thumbnails at its standard widths (https://w.wiki/GHai).
# Every picture is fetched as its original and scaled here: Commons renders
# thumbnails on demand and throttles that to a few files a minute, while the
# originals come straight from its file store.
TIER_SIDE = {"film": 1280, "pool": 500}
TIER_QUALITY = {"film": 82, "pool": 72}

# Summer offsets of the countries the library passes through. A phone stamps its
# wall clock, so a picture in Finland reads an hour ahead of one in Sweden.
SUMMER_OFFSET = {"Finland": "+03:00"}
DEFAULT_OFFSET = "+02:00"

# German words in the trip photographer's file titles, in the English a caption uses.
_TITLE_WORDS = {
    "Fähre": "ferry",
    "Fähranleger": "ferry pier",
    "Hafen": "harbour",
    "Kreuzfahrthafen": "cruise harbour",
    "Aussicht": "view",
    "Naturschutzgebiet": "nature reserve",
    "Kirche": "church",
    "Wasserfall": "waterfall",
    "Leuchtturm": "lighthouse",
    "Aufstieg": "the climb",
    "Wanderweg": "path",
    "nach": "to",
    "Schloss": "castle",
    "Stadtpark": "park",
    "Grenze": "border",
    "Interieur": "inside",
    "Eingang": "entrance",
    "Mündung": "river mouth",
    "Rathaus": "town hall",
    "Flughafen": "airport",
}


@dataclass(frozen=True, slots=True)
class Resolved:
    """What Commons says about one file."""

    title: str
    page: str
    url: str
    mime: str
    width: int
    height: int
    licence: str
    licence_url: str
    artist: str
    taken: str | None
    latitude: float | None
    longitude: float | None
    derivatives: tuple[dict[str, Any], ...] = ()


def plain(html: str) -> str:
    """Commons metadata is HTML; a credit line is text."""
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())


_MONTHS = {
    name: number
    for number, name in enumerate(
        ("january", "february", "march", "april", "may", "june", "july", "august",
         "september", "october", "november", "december"),
        start=1,
    )
}  # fmt: skip


def parse_taken(value: str) -> str | None:
    """A Commons DateTimeOriginal as ``YYYY-MM-DDTHH:MM:SS``, or None when it holds no time.

    Commons gives EXIF's ``2025-07-12 08:33:06`` for most files, and Flickr imports'
    ``Taken on 11 February 2006, 22:24`` for some.
    """
    text = plain(value)
    match = re.search(r"(\d{4})[-:](\d{2})[-:](\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?", text)
    if match:
        year, month, day, hour, minute, second = match.groups()
        return f"{year}-{month}-{day}T{hour}:{minute}:{second or '00'}"
    match = re.search(r"(\d{1,2}) ([A-Za-z]+) (\d{4}),? (\d{2}):(\d{2})(?::(\d{2}))?", text)
    if match and match.group(2).lower() in _MONTHS:
        day, name, year, hour, minute, second = match.groups()
        return f"{year}-{_MONTHS[name.lower()]:02d}-{int(day):02d}T{hour}:{minute}:{second or '00'}"
    return None


def shifted(taken: str, days: int) -> str:
    """Move a wall-clock time by whole days, so the hour and the gaps between shots stay real."""
    return (datetime.fromisoformat(taken) + timedelta(days=days)).isoformat()


def utc_instant(local: str, offset: str) -> str:
    """The UTC instant of a wall-clock time at an offset, in Immich's ``…Z`` form."""
    moment = datetime.fromisoformat(f"{local}{offset}")
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def caption_from_title(title: str) -> str:
    """A plain caption from a Commons title such as ``Ålesund Aksla lub 2025-07-28 img02``."""
    stem = Path(title.removeprefix("File:")).stem
    stem = re.sub(r"\(Unsplash[^)]*\)|\(\d{6,}\)", "", stem)
    stem = re.sub(r"\blub\b|\b\d{4}-\d{2}-\d{2}\b|\b(?:img|mov)\d+\b|\bDSC\w*", "", stem)
    words = [_TITLE_WORDS.get(word, word) for word in stem.replace("_", " ").split()]
    return " ".join(words).strip(" -,") or "a picture from the trip"


def offset_for(country: str | None, default: str) -> str:
    return SUMMER_OFFSET.get(country or "", default)


class Commons:
    """Commons API answers, cached on disk and fetched politely."""

    def __init__(self, cache: Path) -> None:
        self._cache = cache / "commons.json"
        self._known: dict[str, Any] = (
            json.loads(self._cache.read_text()) if self._cache.exists() else {}
        )

    def resolve(self, titles: list[str]) -> dict[str, Resolved]:
        missing = [title for title in titles if title not in self._known]
        for start in range(0, len(missing), 50):
            batch = missing[start : start + 50]
            answer = _get_json(
                API,
                action="query",
                format="json",
                formatversion=2,
                titles="|".join(batch),
                prop="imageinfo|videoinfo",
                iiprop="url|size|mime|extmetadata",
                viprop="derivatives",
            )
            for page in answer["query"]["pages"]:
                self._known[page["title"]] = page
            self._cache.write_text(json.dumps(self._known))
            time.sleep(1.2)
        return {title: _resolved(self._known[title]) for title in titles}


def _resolved(page: dict[str, Any]) -> Resolved:
    if "imageinfo" not in page:
        raise SystemExit(f"{page.get('title')}: not on Commons")
    info = page["imageinfo"][0]
    meta = info.get("extmetadata", {})

    def field(name: str) -> str:
        return str(meta.get(name, {}).get("value", ""))

    latitude, longitude = field("GPSLatitude"), field("GPSLongitude")
    derivatives = tuple(page.get("videoinfo", [{}])[0].get("derivatives", ()))
    return Resolved(
        title=page["title"],
        page=info["descriptionurl"],
        url=info["url"],
        mime=info["mime"],
        width=int(info["width"]),
        height=int(info["height"]),
        licence=plain(field("LicenseShortName")),
        licence_url=field("LicenseUrl"),
        artist=plain(field("Artist")),
        taken=parse_taken(field("DateTimeOriginal")),
        latitude=round(float(latitude), 6) if latitude else None,
        longitude=round(float(longitude), 6) if longitude else None,
        derivatives=derivatives,
    )


class Places:
    """Town and country for a coordinate, asked once per two-decimal cell (about a kilometre)."""

    def __init__(self, cache: Path) -> None:
        self._cache = cache / "places.json"
        self._known: dict[str, list[str]] = (
            json.loads(self._cache.read_text()) if self._cache.exists() else {}
        )

    def name(self, latitude: float, longitude: float) -> tuple[str, str]:
        cell = f"{latitude:.2f},{longitude:.2f}"
        if cell not in self._known:
            answer = _get_json(
                NOMINATIM,
                lat=f"{latitude:.2f}",
                lon=f"{longitude:.2f}",
                zoom=12,
                format="jsonv2",
                **{"accept-language": "en"},
            )
            address = answer.get("address", {})
            town = next(
                (
                    address[key]
                    for key in ("city", "town", "village", "municipality", "hamlet", "county")
                    if key in address
                ),
                "",
            )
            self._known[cell] = [town, address.get("country", "")]
            self._cache.write_text(json.dumps(self._known, ensure_ascii=False))
            time.sleep(1.1)
        town, country = self._known[cell]
        # Brussels communes come back bilingual ("Forest - Vorst"); Immich names a place
        # after one GeoNames town, so the library keeps the first name.
        return town.split(" - ")[0], country


def _get_json(url: str, **params: Any) -> Any:
    return json.loads(_fetch(f"{url}?{urllib.parse.urlencode(params)}"))


class Downloads:
    """Picture bytes by URL, kept on disk so a curation change refetches nothing."""

    def __init__(self, cache: Path) -> None:
        self._dir = cache / "files"
        self._dir.mkdir(parents=True, exist_ok=True)

    def path(self, url: str) -> Path:
        return self._dir / hashlib.sha256(url.encode()).hexdigest()

    def get(self, url: str) -> bytes:
        path = self.path(url)
        if not path.exists():
            path.write_bytes(_fetch(url))
        return path.read_bytes()

    def prefetch(self, urls: list[str]) -> None:
        """Fetch what is missing one file at a time, pausing between requests.

        Commons throttles by address; a steady single queue gets through where
        parallel downloads are refused, and the cache makes a stopped run resume.
        """
        wanted = [url for url in urls if not self.path(url).exists()]
        for done, url in enumerate(wanted, start=1):
            self.get(url)
            time.sleep(_PAUSE_SECONDS)
            if done % 50 == 0:
                print(f"  fetched {done}/{len(wanted)}", flush=True)


_ATTEMPTS = 8
_PAUSE_SECONDS = 1.0
# Some sources store anamorphic pixels; a phone clip's are square, and Immich reports the
# width a player shows, so the stored width must already be that one.
_SQUARE_PIXELS = "scale='trunc(iw*sar/2)*2':ih,setsar=1"


def _fetch(url: str) -> bytes:
    """GET with Wikimedia's etiquette: an identifying agent, and patience when told to wait."""
    for attempt in range(_ATTEMPTS):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310
            with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
                return response.read()
        except urllib.error.HTTPError as error:
            if attempt == _ATTEMPTS - 1 or error.code not in (429, 500, 502, 503, 504):
                raise
            retry_after = error.headers.get("Retry-After", "")
            time.sleep(int(retry_after) if retry_after.isdigit() else min(15 * 2**attempt, 300))
        except OSError:
            if attempt == _ATTEMPTS - 1:
                raise
            time.sleep(2 ** (attempt + 1))
    raise AssertionError("unreachable")


def fetch_url(resolved: Resolved) -> str:
    return resolved.url


def write_picture(data: bytes, tier: str, target: Path) -> tuple[int, int]:
    """Scale to the tier's long side, drop every metadata block, and save as JPEG."""
    from PIL import Image, ImageOps

    side = TIER_SIDE[tier]
    with Image.open(io.BytesIO(data)) as image:
        picture = ImageOps.exif_transpose(image).convert("RGB")
        picture.thumbnail((side, side), Image.Resampling.LANCZOS)
        picture.save(target, "JPEG", quality=TIER_QUALITY[tier], optimize=True, progressive=True)
        return picture.size


def clip_url(resolved: Resolved) -> str:
    """The Commons transcode closest to 720p, so a 4K upload is not fetched whole."""
    webm = sorted(
        (d for d in resolved.derivatives if d.get("type", "").startswith("video/webm")),
        key=lambda d: abs(int(d.get("height", 0)) - 720),
    )
    return webm[0]["src"] if webm else resolved.url


def _probe(path: Path, entries: str) -> dict[str, Any]:
    result = subprocess.run(  # noqa: S603
        ["ffprobe", "-v", "error", "-show_entries", entries, "-of", "json", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def write_clip(source: Path, start: float, seconds: float, target: Path) -> tuple[int, int]:
    """Trim a clip to the moment the library keeps, as a 720p phone-style H.264 clip.

    A phone clip carries sound, and the render keeps it under the music; a source
    without an audio stream gets a silent one rather than none.
    """
    streams = _probe(source, "stream=codec_type,width,height")["streams"]
    video = next(stream for stream in streams if stream["codec_type"] == "video")
    has_audio = any(stream["codec_type"] == "audio" for stream in streams)
    scale = "scale=720:-2" if video["height"] > video["width"] else "scale=-2:720"
    silence = (
        []
        if has_audio
        else ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
    )
    subprocess.run(  # noqa: S603
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-ss", str(start), "-t", str(seconds), "-i", str(source), *silence,
            "-map", "0:v:0", "-map", "0:a:0" if has_audio else "1:a:0", "-shortest",
            "-vf", f"{_SQUARE_PIXELS},{scale},format=yuv420p",
            "-c:v", "libx264", "-preset", "slow", "-crf", "28",
            "-color_range", "tv",
            "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
            # WHY: libx264 writes the colour tags into the stream only through its own
            # parameters; without them a probe reads the transfer as unknown.
            "-x264-params", "colorprim=bt709:transfer=bt709:colormatrix=bt709",
            "-c:a", "aac", "-b:a", "96k", "-ac", "2", "-ar", "48000",
            "-movflags", "+faststart", "-map_metadata", "-1",
            str(target),
        ],
        check=True,
    )  # fmt: skip
    out = _probe(target, "stream=width,height")["streams"][0]
    return int(out["width"]), int(out["height"])


def faces_for(path: Path, people: list[str]) -> list[dict[str, Any]]:
    """The largest faces in a picture, pinned to ``people`` from left to right.

    The fixture decides who is who, so the household groups in the People page
    even though the faces are strangers'. A picture that names more people than
    the detector finds faces is a curation mistake, and the build stops on it.
    """
    import cv2

    sys.path.insert(0, str(ROOT / "src"))
    from immich_memories.processing.scaling_utilities import _yunet_detector

    image = cv2.imread(str(path))
    height, width = image.shape[:2]
    detector = _yunet_detector()
    detector.setInputSize((width, height))
    _, found = detector.detect(image)
    boxes = sorted(
        (tuple(float(v) for v in row[:4]) for row in (found if found is not None else [])),
        key=lambda box: box[2] * box[3],
        reverse=True,
    )[: len(people)]
    if len(boxes) < len(people):
        raise SystemExit(f"{path.name}: {len(people)} people named, {len(boxes)} faces found")
    return [
        {
            "person": person,
            "x": round(x / width, 4),
            "y": round(y / height, 4),
            "w": round(w / width, 4),
            "h": round(h / height, 4),
        }
        for person, (x, y, w, h) in zip(people, sorted(boxes), strict=True)
    ]


def credit_row(record: dict[str, Any]) -> str:
    return (
        f"| `{record['file']}` | {record['source']['title']} | {record['source']['author']} "
        f"| {record['source']['page']} | {record['source']['licence']} "
        f"| `{record['sha256']}` |"
    )


def build(sources: dict[str, Any], cache: Path, library: Path) -> list[dict[str, Any]]:
    sets: dict[str, dict[str, Any]] = sources["sets"]
    entries: list[dict[str, Any]] = sources["pictures"] + sources["clips"]
    commons = Commons(cache)
    places = Places(cache)
    downloads = Downloads(cache)
    resolved = commons.resolve([entry["commons"] for entry in entries])
    downloads.prefetch(
        [fetch_url(resolved[entry["commons"]]) for entry in sources["pictures"]]
        + [clip_url(resolved[entry["commons"]]) for entry in sources["clips"]]
    )
    records = []
    for entry in entries:
        context = _Sources(sets[entry["set"]], places, downloads, library)
        records.append(_record(entry, resolved[entry["commons"]], context))
    records.sort(key=lambda record: (record["taken_utc"], record["stem"]))
    return records


@dataclass(frozen=True, slots=True)
class _Sources:
    group: dict[str, Any]
    places: Places
    downloads: Downloads
    library: Path


def _record(entry: dict[str, Any], source: Resolved, context: _Sources) -> dict[str, Any]:
    group, places, library = context.group, context.places, context.library
    if source.licence not in ACCEPTED_LICENCES:
        raise SystemExit(f"{source.title}: {source.licence!r} is not CC0 or CC BY")
    is_clip = "start" in entry
    if not entry.get("time") and source.taken is None:
        raise SystemExit(f"{source.title}: no capture time on the file; give one with 'time'")
    place = None
    gps_from = None
    if group.get("home_gps"):
        # The owner's rule: one indoor series (one shoot, one interior) may stand in for
        # the household's home, so it is served at the fixture home, and says so.
        place, gps_from = dict(group["home_gps"]), "home"
    elif (
        source.latitude is not None
        and source.longitude is not None
        and not (entry.get("no_gps") or group.get("no_gps"))
    ):
        town, country = places.name(source.latitude, source.longitude)
        place = {
            "latitude": source.latitude,
            "longitude": source.longitude,
            "city": town,
            "country": country,
        }
        gps_from = "file"
    # A curated time is already the served one (the file holds a date or nothing);
    # a file's own time moves by its set's whole days.
    local = entry.get("time") or shifted(str(source.taken), int(group.get("shift_days", 0)))
    offset = offset_for(place["country"] if place else None, group.get("offset", DEFAULT_OFFSET))
    name = f"{entry['stem']}.{'mp4' if is_clip else 'jpg'}"
    target = library / ("clips" if is_clip else "") / name
    target.parent.mkdir(parents=True, exist_ok=True)
    if is_clip:
        clip = context.downloads.path(clip_url(source))
        context.downloads.get(clip_url(source))
        size = write_clip(clip, float(entry["start"]), float(entry["seconds"]), target)
    else:
        data = context.downloads.get(fetch_url(source))
        size = write_picture(data, entry.get("tier", "pool"), target)
    return {
        "stem": entry["stem"],
        "file": str(target.relative_to(library)),
        "kind": "clip" if is_clip else "photo",
        "tier": "film" if is_clip else entry.get("tier", "pool"),
        "set": entry["set"],
        "taken_local": local,
        "utc_offset": offset,
        "taken_utc": utc_instant(local, offset),
        "source_taken": source.taken,
        "gps_from": gps_from,
        "source_gps": (
            [source.latitude, source.longitude] if source.latitude is not None else None
        ),
        "time_from": "file" if not entry.get("time") else "curated",
        "shift_days": int(group.get("shift_days", 0)),
        "place": place,
        "width": size[0],
        "height": size[1],
        "seconds": float(entry["seconds"]) if is_clip else None,
        "caption": entry.get("caption") or caption_from_title(source.title),
        "faces": faces_for(target, entry["people"]) if entry.get("people") and not is_clip else [],
        "people": list(entry.get("people", [])),
        "source": {
            "title": source.title.removeprefix("File:"),
            "page": source.page,
            "author": source.artist,
            "licence": source.licence,
            "licence_url": source.licence_url,
        },
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
    }


def write_credits(records: list[dict[str, Any]], path: Path) -> None:
    header = (path.read_text().split("| File |", 1)[0]) if path.exists() else ""
    lines = [
        header.rstrip() + "\n" if header else "# Where the demo library comes from\n",
        "| File | Title | Author | Source | Licence | SHA-256 |",
        "| --- | --- | --- | --- | --- | --- |",
        *(credit_row(record) for record in sorted(records, key=lambda r: r["file"])),
    ]
    path.write_text("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--library", type=Path, default=LIBRARY_DIR)
    parser.add_argument(
        "--cache", type=Path, default=Path.home() / ".cache" / "immich-memories-fixture"
    )
    args = parser.parse_args(argv)
    args.cache.mkdir(parents=True, exist_ok=True)
    sources = json.loads((args.library / "sources.json").read_text())
    stale = {*args.library.glob("*.jpg"), *args.library.glob("clips/*.mp4")}
    records = build(sources, args.cache, args.library)
    for leftover in stale - {args.library / record["file"] for record in records}:
        leftover.unlink()
    (args.library / "library.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=1) + "\n"
    )
    write_credits(records, args.library / "CREDITS.md")
    print(f"{len(records)} files, {sum(1 for r in records if r['place'])} with GPS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
