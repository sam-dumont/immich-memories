"""What the library measures, named, so a request's words link to it by code.

The catalogue: each entry is a field the library already holds, with the words that name it.
Immich's place names (a name that is also an English word, such as a town called Meadow,
links only when written capitalised mid-sentence), the kind of picture preparation labelled,
the engine's own sharpness line, and how often each person's face is recognised. A request
that names none of these fields gets none of these filters, and every link says why.

The computed selections: each person's first picture (at the onset, never before their
birth) and last picture, the trip farthest from the home of its time, and the day an undated
occasion's pictures show its people together.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from statistics import median
from typing import Protocol

from immich_memories.analysis.trip_detection import DetectedTrip, detect_trips, haversine_km
from immich_memories.api.models import Asset, AssetType, ExifInfo
from immich_memories.free_text.homes import Home
from immich_memories.free_text.lexicon import Lexicon
from immich_memories.free_text.library import LibraryPerson, LibraryPicture, LibraryView
from immich_memories.people.signatures import first_sustained_month

_PLACE_FIELDS = ("country", "region", "city")


@dataclass(frozen=True)
class _Kind:
    words: frozenset[str]
    labels: frozenset[str] = frozenset()
    media_kind: str | None = None

    def holds(self, picture: LibraryPicture) -> bool:
        return picture.picture_kind in self.labels or picture.media_kind == self.media_kind


# How sharp a picture is, by the engine's own line: soft below the library's 10th percentile.
_SHARPNESS = {
    "below": frozenset({"blurry", "blurred", "unfocused", "unsharp", "out of focus", "fuzzy"}),
    "above": frozenset({"sharp", "sharpest", "crisp", "in focus"}),
}
# "in over 35 pictures": people whose face Immich recognised that often. "at least" and "with"
# include the count itself; "over", "more than" and "above" do not.
_FACES_OVER = re.compile(
    r"\b(over|more than|above|at least|with)\s+(\d+)\s+"
    r"(?:pictures|photos|photographs|times|appearances)\b"
)
# Grammar for extremes over time and distance: each asks for a computed selection.
_EXTREMES = {
    "first": frozenset({"first", "earliest"}),
    "last": frozenset({"last", "latest", "most recent"}),
    "farthest": frozenset({"farthest", "furthest"}),
}
# The ordinary picture: named beside a kind ("photos and videos"), it asks for both.
_ORDINARY = frozenset({"photo", "photos", "photograph", "photographs", "picture", "pictures"})
# The kinds of picture the document head labels (videos: Immich's own media kind).
_KINDS = {
    "screenshots": _Kind(
        words=frozenset({"screenshot", "screenshots", "screengrab", "screengrabs"}),
        labels=frozenset({"screenshot_from_computer", "screenshot_from_manual"}),
    ),
    "documents": _Kind(
        words=frozenset({"document", "documents", "scan", "scans", "receipt", "receipts"}),
        labels=frozenset({"full_page_image", "table", "engineering_drawing"}),
    ),
    "maps": _Kind(
        words=frozenset({"map", "maps"}),
        labels=frozenset({"geographical_map", "topographical_map"}),
    ),
    "videos": _Kind(words=frozenset({"video", "videos"}), media_kind="video"),
}
# Words for the picture or the film itself, its kind and its sharpness: the facts above link
# them, so they are never what a picture shows ("sport app screenshots" is about apps).
PICTURE_WORDS = _ORDINARY.union(
    *(kind.words for kind in _KINDS.values()),
    *_SHARPNESS.values(),
    {"image", "images", "memory", "memories", "film", "films", "clip", "clips", "movie", "movies"},
)


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _says(folded_request: str, words: str) -> bool:
    return re.search(rf"\b{re.escape(words)}\b", folded_request) is not None


@dataclass(frozen=True)
class LibraryFacts:
    """The library fields a request names, and the reasoning line for each link."""

    # (field, value): ("country", "Examplia") keeps the pictures Immich placed there.
    places: tuple[tuple[str, str], ...] = ()
    # "screenshots", "documents", "maps", "videos": any of them.
    picture_kinds: tuple[str, ...] = ()
    # "below" or "above" the library's sharpness line.
    sharpness: str | None = None
    sharpness_line: float | None = None
    # People-file persons whose face is recognised as often as the request asks.
    people: tuple[str, ...] = ()
    # "first", "last" or "farthest": the request asks for a computed selection.
    extreme: str | None = None
    reasons: tuple[str, ...] = ()

    def admits(self, picture: LibraryPicture) -> bool:
        """Whether the picture meets every per-picture field the request names."""
        return self.placed(picture) and self.of_kind(picture) and self.sharp_enough(picture)

    def placed(self, picture: LibraryPicture) -> bool:
        """Whether Immich placed the picture in one of the named places (any, when none)."""
        return not self.places or any(
            _fold(getattr(picture, field) or "") == _fold(value) for field, value in self.places
        )

    def of_kind(self, picture: LibraryPicture) -> bool:
        """Whether the picture is one of the named kinds (any, when none is named)."""
        return not self.picture_kinds or any(
            _KINDS[name].holds(picture) for name in self.picture_kinds
        )

    def sharp_enough(self, picture: LibraryPicture) -> bool:
        """Whether the picture sits on the asked side of the sharpness line (any, unasked)."""
        if self.sharpness is None or self.sharpness_line is None:
            return True
        if picture.sharpness is None:
            return False
        below = picture.sharpness < self.sharpness_line
        return below if self.sharpness == "below" else not below


def link_facts(request: str, view: LibraryView, lexicon: Lexicon) -> LibraryFacts:
    """Link the request's words to the fields the library holds, one reason per link."""
    folded = _fold(request)
    places, place_reasons = _places(request, view, lexicon)
    kinds, kind_reasons = _picture_kinds(folded)
    sharpness, sharpness_reasons = _sharpness(folded, view.sharpness_line)
    people, people_reasons = _faces_over(folded, view)
    extreme, extreme_reasons = _extreme(folded)
    return LibraryFacts(
        places=places,
        picture_kinds=kinds,
        sharpness=sharpness,
        sharpness_line=view.sharpness_line,
        people=people,
        extreme=extreme,
        reasons=(
            *place_reasons,
            *kind_reasons,
            *sharpness_reasons,
            *people_reasons,
            *extreme_reasons,
        ),
    )


_Linked = tuple[tuple[str, ...], tuple[str, ...]]


def _picture_kinds(folded: str) -> _Linked:
    if any(_says(folded, word) for word in _ORDINARY):
        return (), ()
    kinds = tuple(
        name for name, kind in _KINDS.items() if any(_says(folded, word) for word in kind.words)
    )
    return kinds, tuple(
        f'"{name}" -> {name} (the kind of picture preparation labels)' for name in kinds
    )


def _extreme(folded: str) -> tuple[str | None, tuple[str, ...]]:
    for name, words in _EXTREMES.items():
        for word in sorted(words):
            if _says(folded, word):
                return name, (f'"{word}" -> the {name} picture, computed',)
    return None, ()


def _faces_over(folded: str, view: LibraryView) -> _Linked:
    said = _FACES_OVER.search(folded)
    if said is None:
        return (), ()
    least = int(said[2]) + (0 if said[1] in {"at least", "with"} else 1)
    counts = Counter(person for picture in view.pictures for person in picture.people)
    chosen = tuple(sorted(p for p in view.people if counts[p] >= least))
    return chosen, (
        f'"{said[0]}" -> the {len(chosen)} people whose face is recognised in at least '
        f"{least} pictures",
    )


def _sharpness(folded: str, line: float | None) -> tuple[str | None, tuple[str, ...]]:
    for side, words in _SHARPNESS.items():
        said = sorted(word for word in words if _says(folded, word))
        if not said:
            continue
        if line is None:
            return None, (f'"{said[0]}" -> nothing: sharpness is not measured in this library yet',)
        return side, (
            f'"{said[0]}" -> {side} the engine\'s own sharpness line ({line:.1f}, the '
            "library's 10th percentile)",
        )
    return None, ()


def _places(
    request: str, view: LibraryView, lexicon: Lexicon
) -> tuple[tuple[tuple[str, str], ...], tuple[str, ...]]:
    names: dict[str, tuple[str, str]] = {}
    for picture in view.pictures:
        for field in _PLACE_FIELDS:
            if value := getattr(picture, field):
                names.setdefault(_fold(value), (field, value))
    folded = _fold(request)
    places = tuple(
        (field, value)
        for name, (field, value) in sorted(names.items())
        if len(name) > 2
        and _says(folded, name)
        and (not lexicon.is_common_word(name) or _written_as_a_name(request, value))
    )
    return places, tuple(
        f'"{value}" -> pictures whose {field} is {value} (Immich\'s place names)'
        for field, value in places
    )


def _written_as_a_name(request: str, name: str) -> bool:
    # A town that is also a word ("Meadow") is that town only when capitalised where a
    # sentence's first word would not be.
    return any(found.start() > 0 for found in re.finditer(rf"\b{re.escape(name)}\b", request))


def _faces_of(pictures: Sequence[LibraryPicture], person: LibraryPerson) -> list[LibraryPicture]:
    # Nobody is photographed before they are born: an earlier face match is someone else.
    born = person.birth_date
    return sorted(
        (
            picture
            for picture in pictures
            if person.person_id in picture.people
            and (born is None or picture.taken_at.date() >= born)
        ),
        key=lambda picture: picture.taken_at,
    )


def first_pictures(
    pictures: Iterable[LibraryPicture], people: Iterable[LibraryPerson]
) -> Mapping[str, LibraryPicture]:
    """Each person's first picture: when they entered the library for good.

    That is the product's onset (the first month with three more inside the following year),
    not a stray older photo, and never before their birth date. Someone who never stayed
    gets their earliest picture.
    """
    held = list(pictures)
    firsts: dict[str, LibraryPicture] = {}
    for person in people:
        faces = _faces_of(held, person)
        if not faces:
            continue
        onset = first_sustained_month({picture.taken_at.date().replace(day=1) for picture in faces})
        firsts[person.person_id] = next(
            (picture for picture in faces if onset and picture.taken_at.date() >= onset),
            faces[0],
        )
    return firsts


def last_pictures(
    pictures: Iterable[LibraryPicture], people: Iterable[LibraryPerson]
) -> Mapping[str, LibraryPicture]:
    """Each person's latest picture with their recognised face: where everyone is now."""
    held = list(pictures)
    return {person.person_id: faces[-1] for person in people if (faces := _faces_of(held, person))}


class TripRules(Protocol):
    """How far and how long a trip is (the `trips` config section)."""

    @property
    def min_distance_km(self) -> float: ...

    @property
    def min_duration_days(self) -> int: ...

    @property
    def max_gap_days(self) -> int: ...


@dataclass(frozen=True)
class FarthestTrip:
    """The trip farthest from home, and its pictures."""

    first_day: date
    last_day: date
    distance_km: float
    asset_ids: frozenset[str]

    @property
    def reason(self) -> str:
        return (
            f'"farthest" -> the trip whose middle photo is farthest from the home of its time: '
            f"{self.distance_km:.0f} km, {self.first_day} to {self.last_day}"
        )


def home_trips(
    pictures: Iterable[LibraryPicture], homes: Sequence[Home], rules: TripRules
) -> list[tuple[Home, DetectedTrip]]:
    """The product's own trips, each detected over one home's years from that home."""
    located = [p for p in pictures if p.latitude is not None and p.longitude is not None]
    found: list[tuple[Home, DetectedTrip]] = []
    for home in homes:
        during = [p for p in located if home.held_on(p.taken_at.date())]
        trips = detect_trips(
            [_trip_asset(picture) for picture in during],
            home.latitude,
            home.longitude,
            min_distance_km=rules.min_distance_km,
            min_duration_days=rules.min_duration_days,
            max_gap_days=rules.max_gap_days,
            name_locations=False,
        )
        found += [(home, trip) for trip in trips]
    return found


def farthest_trip(
    pictures: Iterable[LibraryPicture], homes: Sequence[Home], rules: TripRules
) -> FarthestTrip | None:
    """The trip farthest from the home the owner had when they took it.

    Trips are the product's own trip detection, run over each home's years from that home. A
    trip is as far as its median photo, so one wrong GPS fix cannot make it the farthest.
    """
    held = list(pictures)
    by_id = {picture.asset_id: picture for picture in held}
    best: FarthestTrip | None = None
    for home, trip in home_trips(held, homes, rules):
        far = median(
            haversine_km(home.latitude, home.longitude, *_where(by_id[asset_id]))
            for asset_id in trip.asset_ids
        )
        if best is None or far > best.distance_km:
            best = FarthestTrip(trip.start_date, trip.end_date, far, frozenset(trip.asset_ids))
    return best


def _where(picture: LibraryPicture) -> tuple[float, float]:
    return picture.latitude or 0.0, picture.longitude or 0.0


def _trip_asset(picture: LibraryPicture) -> Asset:
    return Asset(
        id=picture.asset_id,
        type=AssetType.VIDEO if picture.media_kind == "video" else AssetType.IMAGE,
        file_created_at=picture.taken_at,
        file_modified_at=picture.taken_at,
        updated_at=picture.taken_at,
        exif_info=ExifInfo(latitude=picture.latitude, longitude=picture.longitude),
    )


@dataclass(frozen=True)
class OccasionDay:
    """The day an undated occasion happened, or None with the days its words were found on."""

    day: date | None
    photos: int
    reason: str
    # When no day qualifies: up to three days its words were found on, with who was on them.
    found: tuple[tuple[date, int, frozenset[str]], ...] = ()


def occasion_day(
    pictures: Iterable[LibraryPicture], words: Sequence[str], people: Iterable[str]
) -> OccasionDay:
    """The day whose pictures of the occasion show all its people on the photo itself.

    "Our wedding" has no date to read, so it is the day with the most pictures whose caption
    names it and where everyone it belongs to is recognised on that same picture. Presence
    that day proves nothing (a couple spends most days together), and a guest at somebody
    else's wedding, or a framed old photo, shows one of them. Counted on the request's own
    words.
    """
    wanted = frozenset(people)
    said = [re.compile(rf"\b{re.escape(word.lower())}") for word in words]
    of_it = [
        picture
        for picture in pictures
        if picture.caption and any(word.search(picture.caption.lower()) for word in said)
    ]
    together = Counter(picture.taken_at.date() for picture in of_it if wanted <= picture.people)
    asked = ", ".join(words)
    if together:
        day, photos = min(together.items(), key=lambda item: (-item[1], item[0]))
        return OccasionDay(
            day=day,
            photos=photos,
            reason=(
                f"no date known for one occasion -> the day whose photos of {asked} show "
                f"everyone it belongs to on the photo itself: {day} ({photos} photos)"
            ),
        )
    by_day: dict[date, list[LibraryPicture]] = {}
    for picture in of_it:
        by_day.setdefault(picture.taken_at.date(), []).append(picture)
    busiest = sorted(by_day.items(), key=lambda item: (-len(item[1]), item[0]))[:3]
    return OccasionDay(
        day=None,
        photos=0,
        reason=(
            f"not possible: no day's photos of {asked} show everyone it belongs to together "
            f"({len(of_it)} photos name it)"
        ),
        found=tuple(
            (day, len(held), frozenset().union(*(picture.people for picture in held)))
            for day, held in busiest
        ),
    )
