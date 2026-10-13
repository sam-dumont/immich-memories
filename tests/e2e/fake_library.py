"""The household library behind the screenshots, the demo and the e2e tests.

One month, July 2025, told by real photographs and clips from Wikimedia
Commons (``fixtures/library``, built by ``scripts/build_fixture_library.py``
from ``sources.json``; every file is credited in its CREDITS.md). Ten ordinary
days at home in Brussels with a birthday in the middle, then twenty days on the
road north: Denmark, Sweden, the midnight sun at Nordkapp, Lofoten, Værøy, the
Atlantic Road and Geiranger, back by the Kristiansand ferry.

Every picture is served with the place and time its file records. The trip is
one photographer's own holiday, at the minute each shot was taken; the home days
are other photographers' summer days in Brussels, moved by whole days into the
month so the hour of each shot stays true. A picture whose file holds no GPS is
served with none: the location is never made up.

The people are a made-up household. The pictures of them are strangers'
photographs; the build pins each face to a cast member, so Immich's people
groups hold the household even though no two faces are the same person.

This module holds the script on top of the files: which pictures carry which
story, and why every other picture is left out. Moments are pictures of one
set taken without a long gap, so a carrier's alternatives and the bursts around
it come from the photographer's own shots, not from a list.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

LIBRARY_DIR = Path(__file__).parent / "fixtures" / "library"
MANIFEST = LIBRARY_DIR / "library.json"

# A new moment starts when a set goes this long without a picture.
_MOMENT_GAP_SECONDS = 20 * 60
# Two frames this close in one moment are a burst, not two pictures.
_BURST_SECONDS = 15


@dataclass(frozen=True, slots=True)
class Place:
    latitude: float
    longitude: float
    city: str
    country: str
    # The time zone Immich finds from the GPS, which sets the picture's local clock.
    zone: str = "UTC"


# The fixture home is a public landmark, never a real address (owner's rule).
HOME = Place(50.8417, 4.3624, "Brussels", "Belgium", "Europe/Brussels")
# Each country the month passes through, and the zone its pictures' clocks read in.
_ZONES = {
    "Belgium": "Europe/Brussels",
    "Denmark": "Europe/Copenhagen",
    "Sweden": "Europe/Stockholm",
    "Finland": "Europe/Helsinki",
    "Norway": "Europe/Oslo",
    "Germany": "Europe/Berlin",
}
# The set the road trip comes from: one photographer's July 2025 holiday.
TRIP_SET = "north"
# The road north as trip detection reads it from GPS: the ferry home on the 31st
# carries none, so the detected trip ends the day before the last trip picture.
TRIP_DAYS = ("2025-07-12", "2025-07-30")
# The month the library holds, for consumers that ask for it by year and month.
YEAR = 2025
MONTH = 7
MONTH_NAME = "July"

# A made-up household and the people around it. The names are the ones the fake Immich's
# people endpoint returns; the people page fixture keeps its own roster. The household and
# the grandparents clear the people floor; a cousin, two friends' kids and a neighbour
# sit around it; a teenager seen once is the tail a real library has.
CAST: tuple[str, ...] = (
    "Robin",
    "Charlie",
    "Kit",
    "Pat",
    "Lou",
    "Remy",
    "Jo",
    "Alex",
    "Mo",
    "Sasha",
    "Nico",
)
ADULTS = ("Robin", "Charlie")
EVERYONE = CAST


@dataclass(frozen=True, slots=True)
class Story:
    """One weighed story, and the pictures the fixture editor hung on it."""

    key: str
    title: str
    weight: str
    role: str
    purpose: str


STORIES: tuple[Story, ...] = (
    Story(
        key="S0001",
        title="Kit's birthday",
        weight="dominant",
        role="central",
        purpose="The one afternoon the first half of the month was arranged around",
    ),
    Story(
        key="S0002",
        title="The road north",
        weight="major",
        role="central",
        purpose="Twenty days in the car, to Nordkapp and back down the coast",
    ),
    Story(
        key="S0003",
        title="A Sunday in the forest",
        weight="minor",
        role="supporting",
        purpose="One day out between the party and the drive",
    ),
    Story(
        key="S0004",
        title="Ordinary days",
        weight="glimpse",
        role="texture",
        purpose="What the days at home looked like",
    ),
)

STORY_BY_KEY: dict[str, Story] = {story.key: story for story in STORIES}

THESIS = (
    "A month that turns around Kit's birthday at home, then drives north for "
    "twenty days: the midnight sun at Nordkapp, Lofoten, and the Atlantic Road "
    "on the way back down."
)


@dataclass(frozen=True, slots=True)
class Carrier:
    """A picture the scripted editor puts in the cut, and the story it carries."""

    stem: str
    story: str
    favorite: bool = False


# The cut, in capture order. Everything else in the library is left out with a
# reason (``_drop_reason``), most of it as a near-copy or another view of a
# moment the cut already has.
SCRIPT: tuple[Carrier, ...] = (
    Carrier("home-0702-kit-stuffie", "S0004"),
    Carrier("home-0703-duden-07", "S0004"),
    Carrier("birthday-cake", "S0001", favorite=True),
    Carrier("birthday-cupcakes-1", "S0001"),
    Carrier("birthday-superheroes", "S0001"),
    Carrier("birthday-sofa-film", "S0001"),
    Carrier("forest-0706-sonian-2", "S0003"),
    Carrier("forest-0706-picnic", "S0003"),
    Carrier("forest-0706-pat-03", "S0003", favorite=True),
    Carrier("home-0708-ice-cream-bike", "S0004"),
    Carrier("home-0710-sofa", "S0004"),
    Carrier("north-clip-0712-0", "S0002"),
    Carrier("north-0712-0012", "S0002"),
    Carrier("trip-0712-bike-harbour", "S0002"),
    Carrier("north-clip-0715-2", "S0002"),
    Carrier("north-0716-0196", "S0002", favorite=True),
    Carrier("north-0717-0210", "S0002"),
    Carrier("north-0718-0248", "S0002"),
    Carrier("north-0720-0323", "S0002"),
    Carrier("north-0721-0339", "S0002", favorite=True),
    Carrier("north-clip-0723-4", "S0002"),
    Carrier("north-0723-0450", "S0002"),
    Carrier("trip-0723-beach-stones", "S0002"),
    Carrier("north-0725-0556", "S0002"),
    Carrier("north-0726-0644", "S0002"),
    Carrier("north-0728-0825", "S0002"),
    Carrier("north-0729-0898", "S0002"),
)

# Reasons a reader would give that the moment structure cannot: what the
# picture is, not where it sits. Keyed by file stem.
DROP_NOTES: dict[str, str] = {
    "north-0716-0143": "lunch on a plate, could be any café",
    "north-0721-0335": "the cabin dishwasher",
    "north-0726-0564": "the flat tyre: a story told at dinner, not in a film",
    "north-0712-0004": "strangers on the steps, nobody of ours",
}


# The picture the owner edited in Immich's editor, and the one a recent phone saved with an
# HDR gain map: both ordinary days at home, both in the cut.
EDITED_PICTURE = "home-0702-kit-stuffie"
HDR_PICTURE = "home-0710-sofa"


@dataclass(frozen=True, slots=True)
class Face:
    """One face box, in fractions of the picture, pinned to a cast member."""

    person: str
    x: float
    y: float
    w: float
    h: float


@dataclass(frozen=True, slots=True)
class Picture:
    """One capture as the fake Immich serves it, and the line written about it.

    ``taken_at`` is the instant (``fileCreatedAt``, UTC); ``zone`` is where the clock
    stood, from the GPS or, for a picture without one, from its file's offset, so
    ``local_at`` and ``day`` read the wall clock Immich gives as ``localDateTime``.
    ``place`` is None when the file holds no GPS.
    """

    asset_id: str
    filename: str
    kind: str
    taken_at: str
    caption: str
    scene: str
    place: Place | None
    zone: str = "Europe/Brussels"
    width: int = 0
    height: int = 0
    source_file: str = ""
    set_key: str = ""
    is_favorite: bool = False
    people: tuple[str, ...] = ()
    faces: tuple[Face, ...] = ()
    story_key: str | None = None
    drop_reason: str | None = None
    seconds: float = 4.0
    source_id: str | None = None
    sequence: int = 1
    tags: tuple[str, ...] = field(default=())
    portrait: bool = False
    # A photo the owner edited in Immich's editor (served turned, as Immich renders it), a
    # clip with its own recorded sound, and a photo carrying an HDR gain map.
    edited: bool = False
    voiced: bool = False
    hdr: bool = False
    # A Live Photo: the id of its companion clip, and what the clip shows ("moving" content,
    # a "steady" frame, or one take of a "burst" whose clips overlap in time).
    live_video_id: str | None = None
    motion: str = ""
    # For a burst member: where its clip starts in the burst's one continuous recording.
    burst_offset: float = 0.0
    # Served at this exact pixel size instead of the file's own (a screenshot's).
    size: tuple[int, int] | None = None
    # The text Immich's OCR job reads on it, one printed line per line.
    ocr: str = ""

    @property
    def is_video(self) -> bool:
        return self.kind == "video"

    @property
    def source(self) -> Path:
        return LIBRARY_DIR / (self.source_file or f"{self.source_id or self.asset_id}.jpg")

    @property
    def shipped(self) -> bool:
        return self.story_key is not None

    @property
    def local_at(self) -> str:
        """The wall clock where it was taken, as Immich writes ``localDateTime``."""
        local = _instant(self.taken_at).astimezone(ZoneInfo(self.zone)).replace(tzinfo=None)
        return local.isoformat(timespec="milliseconds") + "Z"

    @property
    def day(self) -> str:
        return self.local_at[:10]


def _records() -> list[dict[str, Any]]:
    if not MANIFEST.exists() or not any(LIBRARY_DIR.glob("*.jpg")):
        # WHY loudly: this module IS its directory. A consumer that stages the
        # module without the pictures (the release smoke mounted fake_library.py
        # alone, #881) used to read an empty month and drop every candidate,
        # which surfaces far downstream as "selected no clips".
        raise RuntimeError(
            f"no pictures under {LIBRARY_DIR}: the library is its files, so this "
            "module cannot be used apart from the directory next to it"
        )
    records = json.loads(MANIFEST.read_text())
    return sorted(records, key=lambda record: (record["taken_utc"], record["stem"]))


def _instant(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def _moments(records: list[dict[str, Any]]) -> dict[str, str]:
    """Each stem's moment: its set's run of pictures with no gap over twenty minutes."""
    moment_of: dict[str, str] = {}
    last_seen: dict[str, tuple[datetime, str]] = {}
    for record in records:
        taken = _instant(record["taken_utc"])
        previous = last_seen.get(record["set"])
        if previous is None or (taken - previous[0]).total_seconds() > _MOMENT_GAP_SECONDS:
            key = f"{record['set']}-{record['stem']}"
        else:
            key = previous[1]
        moment_of[record["stem"]] = key
        last_seen[record["set"]] = (taken, key)
    return moment_of


def _place(record: dict[str, Any]) -> Place | None:
    place = record["place"]
    if place is None:
        return None
    zone = _ZONES.get(place["country"], "UTC")
    return Place(place["latitude"], place["longitude"], place["city"], place["country"], zone)


def _zone(record: dict[str, Any], place: Place | None) -> str:
    """The GPS's zone, else the file's own offset read where the set was taken."""
    if place is not None:
        return place.zone
    if record["utc_offset"] == "+03:00":
        return "Europe/Helsinki"
    return "Europe/Oslo" if record["set"] == TRIP_SET else "Europe/Brussels"


def _expand() -> tuple[Picture, ...]:
    records = _records()
    moment_of = _moments(records)
    script = {carrier.stem: carrier for carrier in SCRIPT}
    missing = set(script) - {record["stem"] for record in records}
    if missing:
        raise RuntimeError(f"the script names pictures the library lacks: {sorted(missing)}")
    sequence_in: dict[str, int] = {}
    pictures: list[Picture] = []
    for counter, record in enumerate(records, start=2401):
        stem = record["stem"]
        scene = moment_of[stem]
        sequence_in[scene] = sequence_in.get(scene, 0) + 1
        carrier = script.get(stem)
        video = record["kind"] == "clip"
        place = _place(record)
        pictures.append(
            Picture(
                asset_id=stem,
                filename=f"IMG_{counter}.{'mp4' if video else 'jpg'}",
                kind="video" if video else "still",
                taken_at=record["taken_utc"],
                caption=record["caption"],
                scene=scene,
                place=place,
                zone=_zone(record, place),
                width=record["width"],
                height=record["height"],
                source_file=record["file"],
                set_key=record["set"],
                is_favorite=bool(carrier and carrier.favorite),
                people=tuple(record["people"]),
                faces=tuple(Face(**face) for face in record["faces"]),
                story_key=carrier.story if carrier else None,
                seconds=float(record["seconds"]) if video else 4.0,
                sequence=sequence_in[scene],
                portrait=record["height"] > record["width"],
                edited=stem == EDITED_PICTURE,
                hdr=stem == HDR_PICTURE,
                # Every clip in the library is a phone's own recording, with its sound.
                voiced=video,
            )
        )
    return _with_reasons(pictures)


def _with_reasons(pictures: list[Picture]) -> tuple[Picture, ...]:
    """Give every picture outside the cut the reason the editor left it out."""
    carried_moments = {p.scene for p in pictures if p.shipped}
    carried_days = {p.day for p in pictures if p.shipped}
    moment_sizes: dict[str, int] = {}
    for picture in pictures:
        moment_sizes[picture.scene] = moment_sizes.get(picture.scene, 0) + 1
    previous: Picture | None = None
    out: list[Picture] = []
    for picture in pictures:
        reason = None
        if not picture.shipped:
            context = _Context(previous, carried_moments, carried_days, moment_sizes[picture.scene])
            reason = _drop_reason(picture, context)
        out.append(replace(picture, drop_reason=reason))
        if not picture.is_video:
            previous = picture
    return tuple(out)


@dataclass(frozen=True, slots=True)
class _Context:
    previous: Picture | None
    carried_moments: set[str]
    carried_days: set[str]
    moment_size: int


def _drop_reason(picture: Picture, context: _Context) -> str:
    if picture.asset_id in DROP_NOTES:
        return DROP_NOTES[picture.asset_id]
    previous = context.previous
    if (
        previous is not None
        and previous.scene == picture.scene
        and (_instant(picture.taken_at) - _instant(previous.taken_at)).total_seconds()
        <= _BURST_SECONDS
    ):
        return "a near-copy of the frame before it"
    if picture.scene in context.carried_moments:
        return "another view of a moment already in the cut"
    if "ferry" in picture.caption.lower():
        return "a ferry crossing: sea and sky, the same for an hour"
    where = picture.place.city if picture.place and picture.place.city else None
    if context.moment_size >= 6:
        return f"one of {context.moment_size} shots taken there within minutes" + (
            f", in {where}" if where else ""
        )
    if picture.set_key == TRIP_SET and picture.day in context.carried_days:
        return f"{where}: a day the cut already covers" if where else "a day the cut covers"
    if picture.set_key == TRIP_SET:
        return f"{where}: scenery with nobody of ours in it" if where else "scenery, nobody of ours"
    return "an ordinary moment with no occasion to show"


_EXPANDED: tuple[Picture, ...] = _expand()
_BY_STEM: dict[str, Picture] = {picture.asset_id: picture for picture in _EXPANDED}


def _like(stem: str, **fields: Any) -> Picture:
    """A picture made from a library file: its size, place and zone, with these fields."""
    base = _BY_STEM[stem]
    plain: dict[str, Any] = {
        "source_id": stem,
        "story_key": None,
        "drop_reason": None,
        "people": (),
        "faces": (),
        "is_favorite": False,
        "edited": False,
        "hdr": False,
    }
    return replace(base, **(plain | fields))


def _utc(local: str, zone: str = "Europe/Brussels") -> str:
    moment = datetime.fromisoformat(local).replace(tzinfo=ZoneInfo(zone)).astimezone(UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# A Live Photo's companion clip runs this long, with the shutter in its middle (as an
# iPhone's does).
LIVE_CLIP_SECONDS = 3.0
# A burst's shutters, this far apart: each clip overlaps the next by half.
BURST_STEP_SECONDS = 1.5
# The ordinary Wednesday at home that holds the Live Photos.
LIVE_DAY = "2025-07-09"


def _live(key: str, local: str, caption: str, motion: str, stem: str, **fields: Any) -> Picture:
    """A Live Photo made from a library file: its place (or none) is the file's own."""
    return _like(
        stem,
        asset_id=key,
        filename=f"IMG_{key.upper().replace('-', '_')}.HEIC",
        kind="still",
        taken_at=_utc(local),
        caption=caption,
        scene=key,
        live_video_id=f"{key}-motion",
        motion=motion,
        **fields,
    )


def _burst(index: int) -> Picture:
    seconds = index * BURST_STEP_SECONDS
    return _live(
        f"live-ride-{index + 1}",
        f"{LIVE_DAY}T19:00:{int(seconds):02d}.{int(seconds % 1 * 1000):03d}",
        f"children cycling down the path, take {index + 1}",
        "burst",
        "home-0709-cycle-path",
        burst_offset=seconds,
        story_key="S0004" if index == 0 else None,
        drop_reason=None if index == 0 else "another take of the same burst",
    )


# Live Photos, one ordinary Wednesday: children running through a fountain in motion, a
# sunrise where nothing moves, and a burst of three shots of one ride whose clips overlap.
# Each still ships; the burst ships its first take, and its other takes are what a stitch
# can join to it.
LIVE_PICTURES: tuple[Picture, ...] = (
    _live(
        "live-fountain",
        f"{LIVE_DAY}T12:00:00",
        "children running through the fountain",
        "moving",
        "home-0704-fountain",
        story_key="S0004",
    ),
    _live(
        "live-quiet-sunrise",
        f"{LIVE_DAY}T06:00:00",
        "sunrise over the street, nothing moving",
        "steady",
        "home-0711-sunrise",
        story_key="S0004",
    ),
    *(_burst(index) for index in range(3)),
)

# Everything the fake Immich serves, in capture order: one month, July 2025.
LIBRARY: tuple[Picture, ...] = tuple(
    sorted((*_EXPANDED, *LIVE_PICTURES), key=lambda picture: (picture.taken_at, picture.asset_id))
)
ALL_PICTURES: tuple[Picture, ...] = LIBRARY

BY_ID: dict[str, Picture] = {picture.asset_id: picture for picture in LIBRARY}

# The pictures the scripted editor ships, in capture order, and the story of each.
CARRIERS: tuple[Picture, ...] = tuple(picture for picture in LIBRARY if picture.shipped)
STORY_OF: dict[str, Story] = {
    picture.asset_id: STORY_BY_KEY[picture.story_key]
    for picture in CARRIERS
    if picture.story_key is not None
}

# Everything else, with the reason the editor gave for leaving it out.
DROPPED: dict[str, str] = {
    picture.asset_id: picture.drop_reason or "not part of any story the month tells"
    for picture in LIBRARY
    if not picture.shipped
}

# The trip as the household would file it: every picture of the road north.
TRIP: tuple[Picture, ...] = tuple(p for p in LIBRARY if p.set_key == TRIP_SET)

# The second account's own pictures. Only the partner key reads them, so a film naming
# both accounts holds them and a primary-only film never does; everything above stays the
# primary's library. One shot of the forest Sunday from the other phone, shipped with it.
PARTNER_PICTURES: tuple[Picture, ...] = (
    _like(
        "forest-0706-tervuren-04",
        asset_id="partner-forest-museum",
        filename="PXL_0001.jpg",
        caption="the museum across the water, from the other phone",
        scene="partner-forest-museum",
        story_key="S0003",
    ),
)

# What the scripted editor knows across both accounts.
ACCOUNTS_BY_ID: dict[str, Picture] = BY_ID | {p.asset_id: p for p in PARTNER_PICTURES}
ACCOUNTS_STORY_OF: dict[str, Story] = STORY_OF | {
    p.asset_id: STORY_BY_KEY[p.story_key] for p in PARTNER_PICTURES if p.story_key
}


def carriers_of(story_key: str) -> tuple[Picture, ...]:
    return tuple(picture for picture in CARRIERS if picture.story_key == story_key)


def summary_line() -> str:
    """The line the result page prints: stories that carry pictures, and how many."""
    stories = len({picture.story_key for picture in CARRIERS})
    return f"{stories} stories, {len(CARRIERS)} pictures"


def pool_line() -> str:
    videos = sum(1 for picture in LIBRARY if picture.is_video)
    return f"{len(LIBRARY)} in the pool ({videos} videos, {len(LIBRARY) - videos} photos)"


def _drawn(key: str, local: str, caption: str, drop: str, place: Place, **fields: Any) -> Picture:
    """A picture the fake Immich draws instead of serving a photograph (no one is in it)."""
    return Picture(
        asset_id=key,
        filename=f"IMG_{key.upper().replace('-', '_')}.jpg",
        kind="still",
        taken_at=_utc(local, place.zone),
        caption=caption,
        scene=key,
        place=place,
        zone=place.zone,
        is_favorite=True,
        drop_reason=drop,
        **fields,
    )


# What a phone library also holds and a film must not show, starred so nothing but that rule
# can keep them out: a screenshot (a still at a phone's exact screen size) on the birthday, and
# a campsite registration form photographed on Værøy, whose printed field labels Immich's OCR
# reads. Outside LIBRARY: only a fake Immich started with `held=HELD_PICTURES` serves them, so
# every other test's library stays as it is.
HELD_PICTURES: tuple[Picture, ...] = (
    _drawn(
        "held-screenshot",
        "2025-07-05T14:15:00",
        "a screenshot of a chat on a phone",
        "a screenshot",
        HOME,
        size=(1179, 2556),
    ),
    _drawn(
        "held-form",
        "2025-07-23T15:00:00",
        "a campsite registration form on a table",
        "a personal document",
        _BY_STEM["north-0723-0450"].place or HOME,
        ocr="CAMPSITE REGISTRATION\nName\nDate of birth\nNationality\nSignature",
    ),
)
