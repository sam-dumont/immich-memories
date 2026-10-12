"""A still moves between the whole picture and a real close-up of what the film is about.

The owner's rulings for #2440: every move has the full picture at one end and
its closest frame at the other; a person film pushes in on that person; a group
closes on the tightest crop that keeps every face, or pans across a group too
wide to zoom on; other films zoom in or out per asset, toward the lone face or
the centre. The 5-12 % drift it replaces did not read as a zoom at all.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest

from immich_memories.analysis.framing_target import PictureFaces, picture_faces
from immich_memories.analysis.subject_framing import FaceBox
from immich_memories.api.models import Asset, AssetFace, AssetType, Person
from immich_memories.photos.ken_burns_moves import (
    FACE_AIR,
    MAX_ZOOM,
    MIN_ZOOM,
    PAN_ZOOM,
    SINGLE_ZOOM,
    FilmSubject,
    film_subject,
    pan_for_centre,
    planned_move,
)
from immich_memories.photos.renderer import KenBurnsParams, render_ken_burns_streaming

_W, _H = 1000, 500


def _face(face_id: str, left: int, top: int, size: int) -> AssetFace:
    return AssetFace(
        id=face_id,
        boundingBoxX1=left,
        boundingBoxY1=top,
        boundingBoxX2=left + size,
        boundingBoxY2=top + size,
        imageWidth=_W,
        imageHeight=_H,
    )


def _faces(*people: tuple[str, int, int, int], subjects=()) -> PictureFaces:
    now = datetime(2024, 1, 1, tzinfo=UTC)
    asset = Asset(
        id="a-still",
        type=AssetType.IMAGE,
        fileCreatedAt=now,
        fileModifiedAt=now,
        updatedAt=now,
        people=[
            Person(id=name, name=name, faces=[_face(f"f-{name}", x, y, size)])
            for name, x, y, size in people
        ],
    )
    return picture_faces(asset, subjects)


def _move(faces: PictureFaces, film: FilmSubject, key: str = "a-still") -> KenBurnsParams:
    return planned_move(key, faces, film, fps=10, duration=1.0)


def _frame(zoom: float, pan: tuple[float, float]) -> tuple[float, float, float, float]:
    """The share of the picture a frame at this zoom and pan shows: (left, top, right, bottom)."""
    window = 1.0 / zoom
    cx, cy = (window / 2 + pan[0] * (1 - window), window / 2 + pan[1] * (1 - window))
    return (cx - window / 2, cy - window / 2, cx + window / 2, cy + window / 2)


def _closest(move: KenBurnsParams) -> tuple[float, float, float, float]:
    if move.zoom_end >= move.zoom_start:
        return _frame(move.zoom_end, move.pan_end)
    return _frame(move.zoom_start, move.pan_start)


def _holds(frame, box: FaceBox, air: float = 0.0) -> bool:
    dx, dy = (box.x2 - box.x1) * air, (box.y2 - box.y1) * air
    eps = 1e-6
    return (
        box.x1 - dx >= frame[0] - eps
        and box.y1 - dy >= frame[1] - eps
        and box.x2 + dx <= frame[2] + eps
        and box.y2 + dy <= frame[3] + eps
    )


def _has_full_end(move: KenBurnsParams) -> bool:
    return 1.0 in (move.zoom_start, move.zoom_end)


# ---- what the film is about ----------------------------------------------------


def test_one_name_is_a_person_film_several_a_group_none_other():
    assert film_subject(()) is FilmSubject.OTHER
    assert film_subject(("Kid", "  kid ", None)) is FilmSubject.PERSON
    assert film_subject(("kid", "dad")) is FilmSubject.GROUP


# ---- a person film ---------------------------------------------------------------


class TestPersonFilm:
    def test_opens_on_the_whole_picture_and_pushes_in_on_the_person(self):
        faces = _faces(("kid", 80, 200, 50), ("stranger", 700, 120, 180), subjects=("kid",))

        move = _move(faces, FilmSubject.PERSON)

        assert move.zoom_start == 1.0
        assert SINGLE_ZOOM[0] <= move.zoom_end <= SINGLE_ZOOM[1]
        [kid] = [f for f in faces.faces if f.person_id == "kid"]
        assert _holds(_closest(move), kid, FACE_AIR)

    def test_other_faces_stay_when_they_fit_at_that_zoom(self):
        faces = _faces(("kid", 380, 200, 40), ("dad", 470, 190, 50), subjects=("kid",))

        move = _move(faces, FilmSubject.PERSON)

        assert all(_holds(_closest(move), face) for face in faces.faces)

    def test_a_face_too_big_for_the_zoom_loosens_it(self):
        faces = _faces(("kid", 300, 50, 400), subjects=("kid",))

        move = _move(faces, FilmSubject.PERSON)

        assert MIN_ZOOM <= move.zoom_end < SINGLE_ZOOM[0]


# ---- a group -----------------------------------------------------------------------


class TestGroup:
    def test_closes_on_the_tightest_crop_holding_every_face(self):
        faces = _faces(("a", 300, 200, 40), ("b", 420, 180, 50), ("c", 540, 210, 40))

        move = _move(faces, FilmSubject.GROUP)

        assert move.zoom_start == 1.0
        assert MIN_ZOOM <= move.zoom_end <= MAX_ZOOM
        frame = _closest(move)
        assert all(_holds(frame, face, FACE_AIR) for face in faces.faces)
        # Tightest: any closer and somebody's air is cut.
        tighter = _frame(move.zoom_end * 1.05, move.pan_end)
        if move.zoom_end < MAX_ZOOM:
            assert not all(_holds(tighter, face, FACE_AIR) for face in faces.faces)

    def test_a_group_across_the_picture_is_panned_at_a_fixed_zoom(self):
        faces = _faces(("a", 10, 200, 60), ("b", 470, 200, 60), ("c", 930, 200, 60))

        move = _move(faces, FilmSubject.GROUP)

        assert move.zoom_start == move.zoom_end == PAN_ZOOM
        start, end = _frame(PAN_ZOOM, move.pan_start), _frame(PAN_ZOOM, move.pan_end)
        assert all(_holds(start, face) or _holds(end, face) for face in faces.faces)
        assert abs(move.pan_end[0] - move.pan_start[0]) == 1.0

    def test_several_faces_in_any_other_film_are_a_group(self):
        faces = _faces(("a", 300, 200, 40), ("b", 420, 180, 50))

        move = _move(faces, FilmSubject.OTHER)

        frame = _closest(move)
        assert _has_full_end(move)
        assert all(_holds(frame, face, FACE_AIR) for face in faces.faces)


# ---- other films ---------------------------------------------------------------------


class TestOtherFilms:
    def test_a_lone_face_is_the_closest_frame(self):
        faces = _faces(("someone", 700, 300, 60))

        move = _move(faces, FilmSubject.OTHER)

        assert _has_full_end(move)
        assert _holds(_closest(move), faces.faces[0], FACE_AIR)

    def test_without_a_face_the_zoom_is_clearly_visible_toward_the_centre(self):
        move = _move(PictureFaces(), FilmSubject.OTHER)

        closest = max(move.zoom_start, move.zoom_end)
        assert _has_full_end(move)
        assert closest >= MIN_ZOOM
        assert _closest(move) == pytest.approx(_frame(closest, (0.5, 0.5)))

    def test_stills_vary_between_zooming_in_and_out_but_each_always_moves_the_same(self):
        moves = [_move(PictureFaces(), FilmSubject.OTHER, f"still-{n}") for n in range(40)]

        directions = {move.zoom_end > move.zoom_start for move in moves}
        assert directions == {True, False}
        assert _move(PictureFaces(), FilmSubject.OTHER, "still-7") == moves[7]

    def test_a_memory_film_always_moves_in(self):
        for n in range(20):
            move = _move(PictureFaces(), FilmSubject.GROUP, f"still-{n}")
            assert move.zoom_start == 1.0 < move.zoom_end


def test_pan_for_centre_maps_the_window_centre_into_the_pan_range():
    assert pan_for_centre((0.5, 0.5), 0.6) == pytest.approx((0.5, 0.5))
    assert pan_for_centre((0.3, 0.7), 0.6) == pytest.approx((0.0, 1.0))


# ---- the rendered pixels -------------------------------------------------------------


def _marked() -> np.ndarray:
    """Corner markers, and a white square where the person's face is."""
    img = np.full((_H, _W, 3), 90, dtype=np.uint8)
    img[:40, :40] = (255, 0, 0)
    img[-40:, -40:] = (0, 0, 255)
    img[200:250, 80:130] = 255
    return img


def test_the_rendered_person_film_starts_whole_and_ends_close_on_the_person():
    faces = _faces(("kid", 80, 200, 50), ("stranger", 700, 120, 180), subjects=("kid",))
    move = _move(faces, FilmSubject.PERSON)

    frames = list(render_ken_burns_streaming(_marked(), 400, 200, move, scale_mode="fit"))
    first, last = frames[0], frames[-1]

    assert first[3, 3, 0] > 200 and first[-4, -4, 2] > 200  # both corners: the whole picture
    white = (last >= 250).all(axis=2).sum()
    # The 50-pixel face, drawn at 400/1000 x zoom: about (20 x zoom)^2 pixels.
    assert white > (20 * move.zoom_end) ** 2 * 0.8
    assert last[-4, -4, 2] < 200  # the far corner is gone: a real zoom


def test_the_photo_pipeline_moves_toward_the_film_subject():
    from immich_memories.photos import photo_pipeline

    now = datetime(2024, 1, 1, tzinfo=UTC)
    kid = Person(id="kid", name="Kid", faces=[_face("f1", 80, 200, 50)])
    stranger = Person(id="x", name="Stranger", faces=[_face("f2", 700, 120, 180)])
    asset = Asset(
        id="a-still",
        type=AssetType.IMAGE,
        fileCreatedAt=now,
        fileModifiedAt=now,
        updatedAt=now,
        people=[kid, stranger],
    )

    move = photo_pipeline._ken_burns_params(asset, 10, 1.0, subjects=("Kid", "kid"))

    assert move.zoom_start == 1.0
    kid_box = FaceBox(0.08, 0.4, 0.13, 0.5, named=True, person_id="kid")
    assert _holds(_closest(move), kid_box)
    assert move.pan_end[0] < 0.5
