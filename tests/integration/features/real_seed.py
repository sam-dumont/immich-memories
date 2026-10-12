"""Seed an empty Immich with the library the fake Immich serves, for the real-Immich feature pass.

    uv run python -m tests.integration.features.real_seed --url http://127.0.0.1:2306 \
        --root .immich-gate/features-v3

The files are the fake's own (`fake_immich.generate_media`): the same pixels, clips, Live Photo
motion, gain map and sound, stamped with the capture time and camera a phone writes, so Immich
reads the dates and camera from the file the way it reads a real upload. Then, through Immich's
own API, the seed does by hand what a phone and its owner did: the places, the favourites, each
Live Photo's still linked to its clip, the edit made in Immich's editor, the people's faces, the
lake-week album, and a second account holding the partner's picture and people. No machine
learning runs.

What it leaves under ``--root``: the media, and ``state.json`` (0600), which names the server,
both API keys and the id Immich gave each fixture picture. The feature tests read it through
``FEATURE_IMMICH_STATE`` (`immich_server.py`).

Talks to Immich over plain HTTP with the gate's seeder, never through the product's client:
a product bug must fail a feature test, not the seeding.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

from tests.e2e.fake_immich import (
    ALBUM_ASSETS,
    ALBUM_ID,
    ALBUMS,
    IMMICH_EDIT,
    PARTNER_PEOPLE,
    generate_media,
)
from tests.e2e.fake_library import ALL_PICTURES, CAST, PARTNER_PICTURES, Picture
from tests.integration.immich_gate import media as gate_media
from tests.integration.immich_gate.seed import (
    DEVICE_ID,
    Seeder,
    SeedError,
    _api_key,
    wait_for_immich,
)
from tests.integration.native_sharing.seed import _user

_UPLOAD_WORKERS = 8
_SUBSEC_TIME_ORIGINAL = 0x9291
_SOI = b"\xff\xd8"


@dataclass(frozen=True, slots=True)
class Upload:
    """One file to upload: which fixture asset it is, and on which account."""

    fixture_id: str
    picture: Picture
    path: Path
    partner: bool = False
    # For a Live Photo's clip: the fixture id of the still it belongs to.
    still_id: str | None = None

    @property
    def taken_at(self) -> datetime:
        return gate_media.taken_at(self.picture)

    @property
    def content_type(self) -> str:
        suffix = self.path.suffix.lower()
        return {".mp4": "video/mp4", ".mov": "video/quicktime"}.get(suffix, "image/jpeg")


def _dimensions(path: Path) -> tuple[int, int]:
    """A file's own picture size: what Immich reads, and what a face box is drawn against."""
    if path.suffix.lower() in {".mp4", ".mov"}:
        probe = subprocess.run(  # noqa: S603 -- fixed ffprobe argv, our own media
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=width,height", "-of", "json", str(path)],
            capture_output=True, text=True, check=True,
        )  # fmt: skip
        stream = json.loads(probe.stdout)["streams"][0]
        return int(stream["width"]), int(stream["height"])
    with Image.open(path) as image:
        return image.size


def _stamp_photo(source: Path, target: Path, moment: datetime) -> None:
    """The photo with a camera and its capture time in EXIF, its pixels untouched.

    The EXIF segment goes in after the start-of-image marker, so a gain map appended to the
    file stays where its reader looks for it.
    """
    data = source.read_bytes()
    if not data.startswith(_SOI):
        raise SeedError(f"{source.name} is not a JPEG")
    exif = gate_media._exif(moment, camera=True)
    exif.get_ifd(gate_media._EXIF_IFD)[_SUBSEC_TIME_ORIGINAL] = f"{moment.microsecond // 1000:03d}"
    payload = exif.tobytes()
    segment = b"\xff\xe1" + (len(payload) + 2).to_bytes(2, "big") + payload
    target.write_bytes(_SOI + segment + data[2:])


def _stamp_video(source: Path, target: Path, moment: datetime) -> None:
    """The clip with its capture time, zone and camera as a phone writes them, streams copied."""
    make, model = gate_media.CAMERA
    # The instant in UTC, and the phone's own wall clock with its offset, as an iPhone writes.
    stamp = moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
    local = moment.strftime("%Y-%m-%dT%H:%M:%S") + moment.strftime("%z")
    subprocess.run(  # noqa: S603 -- fixed ffmpeg argv, our own media
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
         "-map", "0", "-c", "copy",
         "-metadata", f"creation_time={stamp}Z",
         "-metadata", f"com.apple.quicktime.creationdate={local}",
         "-metadata", f"com.apple.quicktime.make={make}",
         "-metadata", f"com.apple.quicktime.model={model}",
         "-movflags", "use_metadata_tags+faststart", "-f", "mp4", str(target)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip


def _box(item: Upload, slot: int, width: int, height: int) -> dict[str, int]:
    """Where the face sits: the box the fixture pinned to that person, else one per slot."""
    pinned = [face for face in item.picture.faces if not item.partner]
    if slot < len(pinned):
        face = pinned[slot]
        return {
            "imageWidth": width,
            "imageHeight": height,
            "x": round(face.x * width),
            "y": round(face.y * height),
            "width": round(face.w * width),
            "height": round(face.h * height),
        }
    return {
        "imageWidth": width,
        "imageHeight": height,
        "x": width // 20 + slot * width // 4,
        "y": height // 6,
        "width": width // 6,
        "height": height // 4,
    }


def build_uploads(root: Path) -> list[Upload]:
    """Generate the fake's media under ``root/media`` and stamp each file as a phone would."""
    videos, photos = generate_media(root / "media")
    served = videos | photos
    target = root / "uploads"
    target.mkdir(parents=True, exist_ok=True)
    uploads: list[Upload] = []
    partner_ids = {picture.asset_id for picture in PARTNER_PICTURES}
    for picture in (*ALL_PICTURES, *PARTNER_PICTURES):
        file = target / picture.filename
        if picture.is_video:
            _stamp_video(served[picture.asset_id], file, gate_media.taken_at(picture))
        else:
            _stamp_photo(served[picture.asset_id], file, gate_media.taken_at(picture))
        uploads.append(Upload(picture.asset_id, picture, file, picture.asset_id in partner_ids))
        if picture.live_video_id:
            clip = target / Path(picture.filename).with_suffix(".MOV").name
            _stamp_video(served[picture.live_video_id], clip, gate_media.taken_at(picture))
            uploads.append(Upload(picture.live_video_id, picture, clip, still_id=picture.asset_id))
    return uploads


class _Library:
    """Both accounts' seeders, and the id Immich gave each fixture asset."""

    def __init__(self, url: str) -> None:
        self.primary = Seeder(url, _api_key(url))
        self.partner, self.partner_key = _user(self.primary, url, "partner")
        self.ids: dict[str, str] = {}

    def upload(self, item: Upload) -> None:
        seeder = self.partner if item.partner else self.primary
        created = item.taken_at.isoformat()
        fields = {"fileCreatedAt": created, "fileModifiedAt": created}
        if item.picture.is_favorite and item.still_id is None:
            fields["isFavorite"] = "true"
        if seeder.major < 3:
            fields |= {"deviceId": DEVICE_ID, "deviceAssetId": f"feature-{item.path.name}"}
        with item.path.open("rb") as handle:
            answer = seeder.call(
                "POST",
                "/assets",
                data=fields,
                files={"assetData": (item.path.name, handle, item.content_type)},
            )
        if answer.get("status") == "duplicate":
            raise SeedError(f"Immich took {item.path.name} for a copy of an earlier upload")
        self.ids[item.fixture_id] = answer["id"]

    def describe(self, uploads: list[Upload]) -> None:
        """What the owner did by hand: places, Live Photo links and the editor's edit."""
        for item in uploads:
            seeder = self.partner if item.partner else self.primary
            asset_id = self.ids[item.fixture_id]
            place = item.picture.place
            if place is not None:
                seeder.call(
                    "PUT",
                    f"/assets/{asset_id}",
                    json={"latitude": place.latitude, "longitude": place.longitude},
                )
            if item.still_id is not None:
                seeder.call(
                    "PUT", f"/assets/{self.ids[item.still_id]}", json={"livePhotoVideoId": asset_id}
                )
            if item.picture.edited and item.still_id is None:
                seeder.call("PUT", f"/assets/{asset_id}/edits", json={"edits": [IMMICH_EDIT]})

    def people(self, uploads: list[Upload]) -> dict[str, str]:
        """The cast, a face box per person on each of their pictures; the partner's own people.

        The partner's people are recognised on each of the partner's pictures, as the fake
        says: Immich lists a person only once a face is theirs.
        """
        people = {
            name: self.primary.call("POST", "/people", json={"name": name})["id"] for name in CAST
        }
        partner_people = {}
        for person_id, name, born in PARTNER_PEOPLE:
            body = {"name": name} | ({"birthDate": born} if born else {})
            partner_people[person_id] = self.partner.call("POST", "/people", json=body)["id"]
        featured: set[str] = set()
        for item in uploads:
            if item.still_id is not None:
                continue
            seeder = self.partner if item.partner else self.primary
            on = (
                list(partner_people.values())
                if item.partner
                else [people[name] for name in item.picture.people]
            )
            if not on:
                continue
            asset_id = self.ids[item.fixture_id]
            width, height = _dimensions(item.path)
            for slot, person in enumerate(on):
                seeder.call(
                    "POST",
                    "/faces",
                    json={
                        "assetId": asset_id,
                        "personId": person,
                        **_box(item, slot, width, height),
                    },
                )
                if person not in featured:
                    featured.add(person)
                    seeder.call("PUT", f"/people/{person}", json={"featureFaceAssetId": asset_id})
        return {f"person-{name.lower()}": person for name, person in people.items()} | (
            partner_people
        )

    def album(self) -> dict[str, str]:
        album = self.primary.call("POST", "/albums", json={"albumName": ALBUMS[0]["albumName"]})
        members = sorted(self.ids[fixture_id] for fixture_id in ALBUM_ASSETS)
        self.primary.call("PUT", f"/albums/{album['id']}/assets", json={"ids": members})
        return {ALBUM_ID: album["id"]}


def seed(url: str, root: Path, timeout: float) -> Path:
    started = time.monotonic()
    wait_for_immich(url, timeout)
    root.mkdir(parents=True, exist_ok=True)
    uploads = build_uploads(root)
    library = _Library(url)
    with ThreadPoolExecutor(max_workers=_UPLOAD_WORKERS) as pool:
        list(pool.map(library.upload, uploads))
    # Places and links after the metadata pass, which would otherwise write over them.
    library.primary.wait_for_queues()
    library.describe(uploads)
    people = library.people(uploads)
    albums = library.album()
    library.primary.wait_for_queues()
    state = root / "state.json"
    state.write_text(
        json.dumps(
            {
                "url": url,
                "major": library.primary.major,
                "api_key": library.primary.http.headers["x-api-key"],
                "partner_api_key": library.partner_key,
                "media": str((root / "media").resolve()),
                "asset_ids": library.ids,
                "person_ids": people,
                "album_ids": albums,
            },
            indent=2,
        )
    )
    state.chmod(0o600)
    print(
        f"Seeded Immich v{library.primary.major} at {url} for the feature pass: "
        f"{len(library.ids)} assets on two accounts, {len(people)} people, "
        f"in {time.monotonic() - started:.0f}s"
    )
    return state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=300.0)
    args = parser.parse_args(argv)
    try:
        seed(args.url.rstrip("/"), args.root.resolve(), args.timeout)
    except SeedError as exc:
        print(f"feature seed FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
