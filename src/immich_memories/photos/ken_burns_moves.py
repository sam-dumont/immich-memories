"""Which way a still moves: from the whole picture to its closest frame, or back.

Every move has the whole photograph at one end (zoom 1.0) and its closest frame
at the other. What the closest frame is depends on what the film is about:

* **a person film** pushes in on that person: the closest frame is framed on
  them at a 25-35 % zoom, and the other faces stay only where they still fit;
* **a group** (a film of several people, or several faces in any other film)
  closes on the tightest crop that keeps every face, with air around each head.
  When that crop would barely zoom (the faces span the picture), the move pans
  across the group at a fixed 20 % zoom instead, so everyone is seen on the way;
* **any other film** zooms in or out, chosen per asset, toward its one face, or
  toward the centre when the picture has none.

A memory film moves in; other films vary between in and out. Each still also
gets one of four gentle easings (renderer.EASINGS). Every choice is seeded from
the asset id, so a re-render moves the same way.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from immich_memories.analysis.framing_target import PictureFaces, faces_extent, framing_centre
from immich_memories.analysis.subject_framing import FaceBox
from immich_memories.photos.renderer import EASINGS, KenBurnsParams

# A single subject (a person, a lone face, the centre of a faceless picture)
# fills about three quarters of the frame's width at the closest frame: close
# enough to read as a push-in over a 4-second still, loose enough to keep the
# shoulders and some of the scene.
SINGLE_ZOOM = (1.25, 1.35)
# The photo is prepared at 1.5x the canvas (photo_pipeline), so a closer frame
# would upscale pixels.
MAX_ZOOM = 1.5
# Below this the move reads as drift rather than a zoom (5-12 % was invisible).
MIN_ZOOM = 1.15
# The zoom a pan across a wide group holds from one end to the other.
PAN_ZOOM = 1.2
# Air around a face box on every side, as a share of the box itself: Immich's
# box covers the face, not the hair or chin, and a head touching the frame's
# edge looks cut off.
FACE_AIR = 0.5

_FULL_FRAME = (1.0, (0.5, 0.5))


class FilmSubject(StrEnum):
    """Who the film the still is in is about."""

    PERSON = "person"
    GROUP = "group"
    OTHER = "other"


def film_subject(subjects: Iterable[str | None]) -> FilmSubject:
    """A film naming one person is about them; naming several, about a group."""
    named = {" ".join(subject.split()).casefold() for subject in subjects if subject}
    if not named:
        return FilmSubject.OTHER
    return FilmSubject.PERSON if len(named) == 1 else FilmSubject.GROUP


@dataclass(frozen=True, slots=True)
class _Frame:
    zoom: float
    centre: tuple[float, float]


def planned_move(
    seed_key: str,
    faces: PictureFaces,
    film: FilmSubject,
    *,
    fps: int,
    duration: float,
) -> KenBurnsParams:
    """The move for one still, the same every time for the same picture and film."""
    rng = random.Random(int(hashlib.sha256(seed_key.encode()).hexdigest()[:8], 16))
    single_zoom = rng.uniform(*SINGLE_ZOOM)
    zoom_in = film is not FilmSubject.OTHER or rng.random() < 0.5
    forward = rng.random() < 0.5
    easing = rng.choice(EASINGS)

    padded = _with_air(faces.faces)
    subject = [face for face in padded if face.person_id and face.person_id in faces.subject_ids]
    if film is FilmSubject.PERSON and subject:
        closest = _single(padded, faces.subject_ids, subject, single_zoom)
    elif len(padded) >= 2:
        group = _group(padded)
        if group is None:
            return _pan_across(padded, forward, easing, fps=fps, duration=duration)
        closest = group
    elif padded:
        closest = _single(padded, frozenset(), padded, single_zoom)
    else:
        closest = _Frame(single_zoom, (0.5, 0.5))

    full = _Frame(*_FULL_FRAME)
    start, end = (full, closest) if zoom_in else (closest, full)
    return KenBurnsParams(
        zoom_start=start.zoom,
        zoom_end=end.zoom,
        pan_start=pan_for_centre(start.centre, 1.0 / start.zoom),
        pan_end=pan_for_centre(end.centre, 1.0 / end.zoom),
        fps=fps,
        duration=duration,
        easing=easing,
    )


def pan_for_centre(centre: tuple[float, float], window: float) -> tuple[float, float]:
    """The pan position that puts a ``window``-wide view's centre at ``centre``.

    The renderer reads a pan as a position in the room the zoom leaves: 0 puts
    the view against the left (top) edge, 1 against the right (bottom).
    """
    if window >= 1.0:
        return (0.5, 0.5)
    return (
        min(1.0, max(0.0, (centre[0] - window / 2) / (1.0 - window))),
        min(1.0, max(0.0, (centre[1] - window / 2) / (1.0 - window))),
    )


def _with_air(faces: Sequence[FaceBox]) -> list[FaceBox]:
    padded = []
    for face in faces:
        if face.area <= 0:
            continue
        dx, dy = (face.x2 - face.x1) * FACE_AIR, (face.y2 - face.y1) * FACE_AIR
        padded.append(
            FaceBox(
                max(0.0, face.x1 - dx),
                max(0.0, face.y1 - dy),
                min(1.0, face.x2 + dx),
                min(1.0, face.y2 + dy),
                named=face.named,
                person_id=face.person_id,
            )
        )
    return padded


def _clamped(zoom: float) -> float:
    return min(MAX_ZOOM, max(MIN_ZOOM, zoom))


def _single(
    padded: Sequence[FaceBox],
    subject_ids: Collection[str],
    subject: Sequence[FaceBox],
    drawn: float,
) -> _Frame:
    """Framed on the subject at the drawn zoom, or looser if the subject needs it."""
    needed = max(faces_extent(subject))
    zoom = _clamped(min(drawn, 1.0 / needed) if needed > 0 else drawn)
    window = 1.0 / zoom
    return _Frame(zoom, framing_centre(padded, subject_ids, (window, window)))


def _group(padded: Sequence[FaceBox]) -> _Frame | None:
    """The tightest crop holding every face, or None when it would barely zoom."""
    width, height = faces_extent(padded)
    tight = 1.0 / max(width, height)
    if tight < MIN_ZOOM:
        return None
    zoom = min(MAX_ZOOM, tight)
    centre = (
        (min(f.x1 for f in padded) + max(f.x2 for f in padded)) / 2,
        (min(f.y1 for f in padded) + max(f.y2 for f in padded)) / 2,
    )
    window = 1.0 / zoom
    return _Frame(zoom, framing_centre(padded, frozenset(), (window, window), toward=centre))


def _pan_across(
    padded: Sequence[FaceBox], forward: bool, easing: str, *, fps: int, duration: float
) -> KenBurnsParams:
    """A pan from one end of a wide group to the other, at a fixed zoom."""
    width, height = faces_extent(padded)
    window = 1.0 / PAN_ZOOM
    centre = framing_centre(padded, frozenset(), (window, window))
    across = pan_for_centre(centre, window)
    ends = (
        ((0.0, across[1]), (1.0, across[1]))
        if width >= height
        else (
            (across[0], 0.0),
            (across[0], 1.0),
        )
    )
    start, end = ends if forward else ends[::-1]
    return KenBurnsParams(
        zoom_start=PAN_ZOOM,
        zoom_end=PAN_ZOOM,
        pan_start=start,
        pan_end=end,
        fps=fps,
        duration=duration,
        easing=easing,
    )
