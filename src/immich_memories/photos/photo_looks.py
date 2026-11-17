"""How a still meets a canvas of another shape: the looks `defaults.scale_mode` offers.

* ``blur``: the whole picture, centred, with its own blurred copy in the bands;
* ``fit``: the whole picture, with black bands;
* ``crop``: the picture fills the canvas. Its long side is cut around the faces the
  framing rule picks (the film's person when they show, else every face), or around
  the centre when nobody is in it, and the move runs on what is left;
* ``auto``: ``crop`` for a picture with faces, ``blur`` for one without.

A crop never cuts the faces it is framed on. When they cannot all fit, or the crop
holds too few pixels for the move's closest frame, the still keeps the blur. Videos
have no crop: under ``crop`` and ``auto`` they keep the blur.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from immich_memories.analysis.facts.framing_target import PictureFaces, faces_extent, framing_centre
from immich_memories.analysis.facts.subject_framing import FaceBox
from immich_memories.photos.ken_burns_moves import FilmSubject, planned_move, with_air
from immich_memories.photos.renderer import KenBurnsParams

logger = logging.getLogger(__name__)

_CROPPING = frozenset({"crop", "auto"})
# A fitted picture this close to the canvas already fills it (the renderer's own tolerance).
_FILLS_WITHIN_PX = 2
# The photo is prepared at 1.5x the canvas so the closest frame never upscales.
_PREPARED_SCALE = 1.5
_EPS = 1e-6


@dataclass(frozen=True, slots=True)
class CropWindow:
    """The part of the picture a crop keeps, in shares of the picture."""

    left: float
    top: float
    width: float
    height: float

    def holds(self, face: FaceBox) -> bool:
        return (
            face.x1 >= self.left - _EPS
            and face.y1 >= self.top - _EPS
            and face.x2 <= self.left + self.width + _EPS
            and face.y2 <= self.top + self.height + _EPS
        )

    def within(self, face: FaceBox) -> FaceBox:
        """The face in the crop's own shares, clipped to it."""

        def axis(value: float, start: float, size: float) -> float:
            return min(1.0, max(0.0, (value - start) / size))

        return FaceBox(
            axis(face.x1, self.left, self.width),
            axis(face.y1, self.top, self.height),
            axis(face.x2, self.left, self.width),
            axis(face.y2, self.top, self.height),
            named=face.named,
            person_id=face.person_id,
        )


@dataclass(frozen=True, slots=True)
class FramedStill:
    """What a still's frames are cut from under a look, the move over it and its bands' fill."""

    pixels: np.ndarray
    params: KenBurnsParams
    fill: str
    cropped: bool = False


def prepared_box(look: str, canvas: tuple[int, int], *, has_faces: bool) -> tuple[int, int]:
    """The box a still is decoded into: wide enough that a crop still fills the canvas sharply."""
    width, height = canvas
    if look == "crop" or (look == "auto" and has_faces):
        # A crop keeps the picture's whole short side, which must then cover the canvas's
        # matching side at 1.5x, however tall the picture is.
        if width >= height:
            return round(width * _PREPARED_SCALE), round(width * _PREPARED_SCALE * width / height)
        return round(height * _PREPARED_SCALE * height / width), round(height * _PREPARED_SCALE)
    return round(width * _PREPARED_SCALE), round(height * _PREPARED_SCALE)


def crop_window(
    faces: PictureFaces,
    film: FilmSubject,
    picture: tuple[int, int],
    canvas: tuple[int, int],
    look: str,
) -> CropWindow | None:
    """The crop that fills the canvas under ``look``, or None to keep the whole picture."""
    if look not in _CROPPING:
        return None
    pw, ph = picture
    cw, ch = canvas
    fit = min(cw / pw, ch / ph)
    if int(pw * fit) >= cw - _FILLS_WITHIN_PX and int(ph * fit) >= ch - _FILLS_WITHIN_PX:
        return None
    share = (min(1.0, (cw / ch) / (pw / ph)), min(1.0, (pw / ph) / (cw / ch)))
    padded = with_air(faces.faces)
    if padded:
        return _around_faces(padded, faces, film, share)
    if look == "auto":
        return None
    return CropWindow((1.0 - share[0]) / 2, (1.0 - share[1]) / 2, *share)


def _around_faces(
    padded: list[FaceBox], faces: PictureFaces, film: FilmSubject, share: tuple[float, float]
) -> CropWindow | None:
    """A ``share``-sized crop holding the faces the framing rule picks, or None when it can't."""
    subject_ids = faces.subject_ids if film is FilmSubject.PERSON else frozenset()
    subject = [face for face in padded if face.person_id and face.person_id in subject_ids]
    kept = subject or padded
    need = faces_extent(kept)
    if need[0] > share[0] + _EPS or need[1] > share[1] + _EPS:
        return None
    toward = None
    if not subject:
        toward = (
            (min(f.x1 for f in kept) + max(f.x2 for f in kept)) / 2,
            (min(f.y1 for f in kept) + max(f.y2 for f in kept)) / 2,
        )
    centre = framing_centre(padded, subject_ids if subject else frozenset(), share, toward=toward)
    window = CropWindow(centre[0] - share[0] / 2, centre[1] - share[1] / 2, *share)
    # The rule above keeps them; this keeps a face from ever being cut if it did not.
    return window if all(window.holds(face) for face in kept) else None


def framed_still(
    seed_key: str,
    pixels: np.ndarray,
    faces: PictureFaces,
    film: FilmSubject,
    canvas: tuple[int, int],
    look: str,
    *,
    fps: int,
    duration: float,
) -> FramedStill:
    """The still as ``look`` shows it on ``canvas``, with the move planned on what is shown."""
    fill = "fit" if look == "fit" else "blur"
    ph, pw = pixels.shape[:2]
    window = crop_window(faces, film, (pw, ph), canvas, look)
    if window is not None:
        x0, y0 = round(window.left * pw), round(window.top * ph)
        x1 = max(x0 + 1, round((window.left + window.width) * pw))
        y1 = max(y0 + 1, round((window.top + window.height) * ph))
        cropped = np.ascontiguousarray(pixels[y0:y1, x0:x1])
        inside = PictureFaces(
            tuple(box for box in (window.within(face) for face in faces.faces) if box.area > 0),
            faces.subject_ids,
        )
        params = planned_move(
            seed_key, inside, film, fps=fps, duration=duration, portrait=y1 - y0 > x1 - x0
        )
        closest = max(params.zoom_start, params.zoom_end)
        if (x1 - x0) >= canvas[0] * closest - 1:
            return FramedStill(cropped, params, fill, cropped=True)
        logger.info(
            "A still has too few pixels to fill the frame at its closest; it keeps the blur"
        )
    params = planned_move(seed_key, faces, film, fps=fps, duration=duration, portrait=ph > pw)
    return FramedStill(pixels, params, fill)
