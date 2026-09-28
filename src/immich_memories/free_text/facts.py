"""What the library measures, named, so a request's words link to it by code.

Each entry is a field the library already holds, with the words that name it: the place names
Immich gives each picture (a name that is also an English word, such as a town called Meadow,
links only when written capitalised mid-sentence). A request that names none of these fields gets none of these
filters, and every link says why it was made.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

from immich_memories.free_text.lexicon import Lexicon
from immich_memories.free_text.library import LibraryPicture, LibraryView

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
        placed = not self.places or any(
            _fold(getattr(picture, field) or "") == _fold(value) for field, value in self.places
        )
        kind = not self.picture_kinds or any(
            _KINDS[name].holds(picture) for name in self.picture_kinds
        )
        return placed and kind and self._sharp_enough(picture)

    def _sharp_enough(self, picture: LibraryPicture) -> bool:
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
