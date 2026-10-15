"""Where a zoomed window over a picture should sit, read off the faces in it.

A memory about somebody ends its moves on that person's face; a memory about
nobody in particular ends them on the largest face. Either way the other faces
in the picture stay in the window when it can hold them, nearest first, and the
subject's face is the one that stays when it cannot. With no face at all the
window sits in the middle.

The photo Ken Burns move places its window by this rule.
Coordinates are shares of the picture's own width and height (0 to 1).
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from immich_memories.analysis.facts.subject_framing import FaceBox, face_box


@dataclass(frozen=True, slots=True)
class PictureFaces:
    """A picture's faces, and the people among them the memory is about."""

    faces: tuple[FaceBox, ...] = ()
    subject_ids: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class _Extent:
    x1: float
    y1: float
    x2: float
    y2: float

    @classmethod
    def of(cls, faces: Iterable[FaceBox]) -> _Extent:
        boxes = list(faces)
        return cls(
            min(face.x1 for face in boxes),
            min(face.y1 for face in boxes),
            max(face.x2 for face in boxes),
            max(face.y2 for face in boxes),
        )

    def joined(self, face: FaceBox) -> _Extent:
        return _Extent(
            min(self.x1, face.x1),
            min(self.y1, face.y1),
            max(self.x2, face.x2),
            max(self.y2, face.y2),
        )

    def fits(self, window: tuple[float, float]) -> bool:
        return self.x2 - self.x1 <= window[0] and self.y2 - self.y1 <= window[1]


def _normalized_name(name: str) -> str:
    return " ".join(name.split()).casefold()


def picture_faces(asset: Any, subjects: Iterable[str | None]) -> PictureFaces:
    """An Immich asset's faces, each tied to its person, and which are the memory's.

    ``subjects`` name the people the memory is about, by person id or by name
    (compared without case or extra spaces). Immich nests a face box under the
    person it belongs to, in the pixels of the rendition it detected on; each box
    is normalised by that rendition, never by the original's size.
    """
    wanted = {_normalized_name(subject) for subject in subjects if subject}
    faces: list[FaceBox] = []
    subject_ids: set[str] = set()
    seen: set[str] = set()
    for person, face in _faces_with_people(asset):
        face_id = getattr(face, "id", None)
        if face_id is not None and face_id in seen:
            continue
        if face_id is not None:
            seen.add(face_id)
        box = face_box(face, person)
        if box is None:
            continue
        faces.append(box)
        if box.person_id and wanted & {box.person_id.casefold(), _normalized_name(person.name)}:
            subject_ids.add(box.person_id)
    return PictureFaces(tuple(faces), frozenset(subject_ids))


def _faces_with_people(asset: Any) -> Iterable[tuple[Any, Any]]:
    for person in getattr(asset, "people", None) or ():
        for face in getattr(person, "faces", None) or ():
            yield person, face
    for face in getattr(asset, "faces", None) or ():
        yield getattr(face, "person", None), face


def faces_extent(faces: Sequence[FaceBox]) -> tuple[float, float]:
    """The width and height of the smallest box holding every face; zero for none."""
    usable = [face for face in faces if face.area > 0]
    if not usable:
        return (0.0, 0.0)
    extent = _Extent.of(usable)
    return (extent.x2 - extent.x1, extent.y2 - extent.y1)


def framing_centre(
    faces: Sequence[FaceBox],
    subject_ids: Collection[str],
    window: tuple[float, float],
    *,
    toward: tuple[float, float] | None = None,
) -> tuple[float, float]:
    """The centre of a ``window``-sized view that frames the subject and keeps the rest.

    The subject is every face of the people in ``subject_ids``, or the largest
    face when none of them shows. The other faces join it nearest first, as long
    as everything joined still fits the window. The view then sits as close to
    ``toward`` (the subject's centre unless given) as keeping all that inside
    allows, and never past the picture's edges.
    """
    usable = [face for face in faces if face.area > 0]
    if not usable:
        return (0.5, 0.5)
    subject = [face for face in usable if face.person_id and face.person_id in subject_ids]
    if not subject:
        subject = [max(usable, key=lambda face: face.area)]
    kept = _Extent.of(subject)
    anchor = ((kept.x1 + kept.x2) / 2, (kept.y1 + kept.y2) / 2)
    others = [face for face in usable if not any(face is chosen for chosen in subject)]
    for face in sorted(others, key=lambda face: _distance_key(face, anchor)):
        joined = kept.joined(face)
        if joined.fits(window):
            kept = joined
    aim = anchor if toward is None else toward
    return (
        _axis_centre(aim[0], kept.x1, kept.x2, window[0]),
        _axis_centre(aim[1], kept.y1, kept.y2, window[1]),
    )


def _distance_key(face: FaceBox, anchor: tuple[float, float]) -> tuple[float, float, float, float]:
    cx, cy = (face.x1 + face.x2) / 2, (face.y1 + face.y2) / 2
    # Ties go to the larger face, then to position, so the choice never depends on order.
    return ((cx - anchor[0]) ** 2 + (cy - anchor[1]) ** 2, -face.area, face.x1, face.y1)


def _axis_centre(anchor: float, low: float, high: float, window: float) -> float:
    half = min(window, 1.0) / 2
    lowest, highest = half, 1.0 - half
    if high - low <= window:
        # Every centre in this range keeps [low, high] inside the view.
        lowest, highest = max(high - half, lowest), min(low + half, highest)
    return min(max(anchor, lowest), highest)
