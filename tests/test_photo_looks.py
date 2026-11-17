"""The crop and auto looks fill the frame with a photo of the other shape, around its faces.

`blur` and `fit` keep the whole picture with bands; `crop` cuts the picture's long
side around the faces the framing rule picks and runs the move on what is left;
`auto` crops a picture with faces and keeps the blur for one without. A crop never
cuts those faces: when they cannot fit, or the crop is too small for the move, the
still keeps the blur. Frames come from the real renderer and are read by sampling
pixels.
"""

from __future__ import annotations

import numpy as np
import pytest

from immich_memories.analysis.facts.framing_target import PictureFaces
from immich_memories.analysis.facts.subject_framing import FaceBox
from immich_memories.config.models.render import DefaultsConfig, video_fill
from immich_memories.photos.ken_burns_moves import FilmSubject
from immich_memories.photos.photo_looks import crop_window, framed_still, prepared_box
from immich_memories.photos.renderer import crop_window as view_at
from immich_memories.photos.renderer import ken_burns_frames, ken_burns_layers, move_frames

CANVAS = (320, 180)
# A portrait photo, prepared at 1.5x the canvas's width.
PICTURE = (480, 640)
BAND = (90, 160, 30)  # a solid colour, so a band of its blur reads as this colour
FACE = (240, 40, 40)
KID = FaceBox(0.40, 0.62, 0.60, 0.77, named=True, person_id="kid")


def _photo(face: FaceBox | None) -> np.ndarray:
    picture = np.empty((PICTURE[1], PICTURE[0], 3), dtype=np.uint8)
    picture[:] = BAND
    if face is not None:
        w, h = PICTURE
        picture[
            round(face.y1 * h) : round(face.y2 * h), round(face.x1 * w) : round(face.x2 * w)
        ] = FACE
    return picture


def _faces(*boxes: FaceBox, subject: str | None = "kid") -> PictureFaces:
    return PictureFaces(tuple(boxes), frozenset({subject}) if subject else frozenset())


def _frames(look: str, faces: PictureFaces, picture: np.ndarray, film=FilmSubject.PERSON):
    still = framed_still("a-still", picture, faces, film, CANVAS, look, fps=10, duration=1.0)
    layers = ken_burns_layers(still.pixels, *CANVAS, still.params, scale_mode=still.fill)
    return still, list(ken_burns_frames(layers, still.params))


def _band_is_picture_edge(frame: np.ndarray) -> bool:
    """The outer columns hold the picture itself, not a band beside it."""
    edges = np.concatenate([frame[:, :8], frame[:, -8:]], axis=1).reshape(-1, 3).astype(int)
    return bool(np.abs(edges - BAND).max() <= 2)


def test_crop_fills_the_frame_and_keeps_the_face_in_it_for_the_whole_move():
    still, frames = _frames("crop", _faces(KID), _photo(KID))

    assert still.cropped
    # The crop has the canvas's shape: nothing for bands to fill.
    h, w = still.pixels.shape[:2]
    assert abs(w / h - CANVAS[0] / CANVAS[1]) < 0.01
    for i, frame in enumerate(frames):
        assert frame.shape[:2] == (CANVAS[1], CANVAS[0])
        assert _band_is_picture_edge(frame), i
        reds = np.argwhere(np.all(np.abs(frame.astype(int) - FACE) <= 2, axis=2))
        assert len(reds), f"the face left frame {i}"
        top, left = reds.min(axis=0)
        bottom, right = reds.max(axis=0)
        # The whole face, not a sliver at an edge.
        assert top > 0 and bottom < CANVAS[1] - 1 and left > 0 and right < CANVAS[0] - 1, i


def test_the_crop_is_framed_on_the_face_not_the_centre():
    still, frames = _frames("crop", _faces(KID), _photo(KID))
    middle = frames[0]
    reds = np.argwhere(np.all(np.abs(middle.astype(int) - FACE) <= 2, axis=2))
    # Low in the picture, the face still sits well inside the cropped frame.
    assert CANVAS[1] * 0.15 < reds[:, 0].mean() < CANVAS[1] * 0.85


def test_blur_keeps_the_whole_portrait_between_bands():
    still, frames = _frames("blur", _faces(KID), _photo(KID))

    assert not still.cropped
    assert still.pixels.shape[:2] == (PICTURE[1], PICTURE[0])
    layers = ken_burns_layers(still.pixels, *CANVAS, still.params, scale_mode=still.fill)
    assert layers.letterboxed and layers.blur is not None


def test_auto_crops_a_photo_with_faces():
    still, frames = _frames("auto", _faces(KID), _photo(KID))

    assert still.cropped
    assert all(_band_is_picture_edge(frame) for frame in frames)


def test_auto_keeps_the_blur_bands_for_a_photo_without_faces():
    picture = _photo(None)
    picture[:, : PICTURE[0] // 2] = (200, 200, 200)  # two halves, so a band shows as a blur
    still, frames = _frames("auto", PictureFaces(), picture)

    assert not still.cropped
    assert still.fill == "blur"
    layers = ken_burns_layers(still.pixels, *CANVAS, still.params, scale_mode=still.fill)
    assert layers.letterboxed and layers.blur is not None
    x, _y, w, _h = layers.window
    # The band left of the picture is the picture's blur, not black.
    assert frames[0][:, : x - 1].mean() > 30


def test_crop_without_faces_cuts_around_the_centre():
    window = crop_window(PictureFaces(), FilmSubject.OTHER, PICTURE, CANVAS, "crop")

    assert window is not None
    assert window.left == 0 and window.width == 1
    assert window.top == pytest.approx((1 - window.height) / 2)


def test_faces_that_cannot_fit_keep_the_whole_picture():
    # Two people at the top and bottom of a portrait: no landscape crop holds both.
    top = FaceBox(0.4, 0.05, 0.6, 0.18, named=True, person_id="a")
    bottom = FaceBox(0.4, 0.82, 0.6, 0.95, named=True, person_id="b")
    faces = PictureFaces((top, bottom), frozenset())

    for look in ("crop", "auto"):
        assert crop_window(faces, FilmSubject.GROUP, PICTURE, CANVAS, look) is None
        still, _ = _frames(look, faces, _photo(None), film=FilmSubject.GROUP)
        assert not still.cropped and still.fill == "blur"


def test_a_person_film_keeps_its_person_and_may_lose_a_stranger():
    stranger = FaceBox(0.4, 0.05, 0.6, 0.18, named=True, person_id="x")
    faces = _faces(KID, stranger)

    window = crop_window(faces, FilmSubject.PERSON, PICTURE, CANVAS, "crop")

    assert window is not None and window.holds(KID)
    assert not window.holds(stranger)


def test_a_crop_too_small_for_the_move_keeps_the_blur():
    # Prepared at the canvas's own width: the closest frame would upscale the crop.
    small = np.ascontiguousarray(_photo(KID)[::2, ::2][:, : CANVAS[0]])
    still = framed_still(
        "a-still", small, _faces(KID), FilmSubject.PERSON, CANVAS, "crop", fps=10, duration=1.0
    )

    assert not still.cropped and still.fill == "blur"


def test_a_picture_that_already_fills_the_canvas_is_not_cropped():
    assert crop_window(_faces(KID), FilmSubject.PERSON, (640, 360), CANVAS, "crop") is None


@pytest.mark.parametrize("look", ["crop", "auto"])
def test_the_move_on_a_crop_stays_inside_it(look):
    still, _ = _frames(look, _faces(KID), _photo(KID))
    for t in np.linspace(0, 1, 11):
        cx, cy, size = view_at(still.params, float(t))
        assert size / 2 - 1e-9 <= cx <= 1 - size / 2 + 1e-9
        assert size / 2 - 1e-9 <= cy <= 1 - size / 2 + 1e-9


def test_a_crop_is_cut_the_same_by_the_gpu_path_as_by_the_cpu():
    """The crop happens before the layers, so the GPU cuts the frame-filling case it already
    cuts for a landscape still; `move_frames` hands it the same views (#2760)."""
    still, cpu = _frames("crop", _faces(KID), _photo(KID))
    layers = ken_burns_layers(still.pixels, *CANVAS, still.params, scale_mode=still.fill)

    assert not layers.letterboxed and layers.blur is None
    for frame, reference in zip(move_frames(layers, still.params), cpu, strict=True):
        np.testing.assert_array_equal(frame, reference)


def test_a_crop_decodes_the_photo_wide_enough_to_fill_the_frame():
    assert prepared_box("blur", (1920, 1080), has_faces=True) == (2880, 1620)
    assert prepared_box("auto", (1920, 1080), has_faces=False) == (2880, 1620)
    assert prepared_box("crop", (1920, 1080), has_faces=False) == (2880, 5120)
    assert prepared_box("auto", (1080, 1920), has_faces=True) == (5120, 2880)


@pytest.mark.parametrize("look", ["crop", "auto"])
def test_the_new_looks_validate_and_videos_keep_the_blur(look):
    assert DefaultsConfig(scale_mode=look).scale_mode == look
    assert video_fill(look) == "blur"
    assert video_fill("fit") == "fit"


@pytest.mark.parametrize(("retired", "meaning"), [("fill", "fit"), ("smart_crop", "blur")])
def test_the_retired_names_keep_their_old_meaning(retired, meaning):
    assert DefaultsConfig(scale_mode=retired).scale_mode == meaning


def test_the_default_look_is_still_blur():
    assert DefaultsConfig().scale_mode == "blur"


def _scale_mode_choices(*path: str) -> list[str]:
    from immich_memories.cli import main

    command = main
    for name in path:
        command = command.commands[name]
    option = next(p for p in command.params if p.name == "scale_mode")
    return list(option.type.choices)


@pytest.mark.parametrize("path", [("generate",), ("runs", "render")])
def test_the_cli_offers_the_new_looks_and_not_the_retired_names(path):
    choices = _scale_mode_choices(*path)

    assert {"blur", "fit", "crop", "auto"} == set(choices)
