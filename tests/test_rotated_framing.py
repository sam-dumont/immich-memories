"""A manual rotation turns the face boxes with the picture before the crop frames them.

Issue #2444: a clip with a rotation override is turned by FFmpeg before the
smart-zoom crop, but the face boxes (Immich's and the detector's) were read on
the unturned picture, so the crop aimed where the face used to be. These tests
turn real pixels with the encoder's own FFmpeg rotation filter, so the direction
is proven against what FFmpeg does, not assumed.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from immich_memories.analysis.framing_target import PictureFaces, rotated_faces
from immich_memories.analysis.subject_framing import FaceBox
from immich_memories.processing.assembly_config import (
    AssemblyClip,
    AssemblySettings,
    _get_rotation_filter,
    standalone_assembly_encoding_plan,
)
from immich_memories.processing.clip_encoder import ClipEncoder

_SRC_W, _SRC_H = 640, 360
# A white "face" against the left edge, a little above the middle, on black.
_FACE = FaceBox(0.02, 0.30, 0.12, 0.48, named=True, person_id="kid")


def _picture(path: Path) -> Path:
    pixels = np.zeros((_SRC_H, _SRC_W, 3), dtype=np.uint8)
    x1, x2 = round(_FACE.x1 * _SRC_W), round(_FACE.x2 * _SRC_W)
    y1, y2 = round(_FACE.y1 * _SRC_H), round(_FACE.y2 * _SRC_H)
    pixels[y1:y2, x1:x2] = 255
    Image.fromarray(pixels).save(path)
    return path


def _ffmpeg(source: Path, video_filter: str, output: Path) -> np.ndarray:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(source), "-vf", video_filter, str(output)],
        check=True,
        capture_output=True,
    )
    return np.asarray(Image.open(output).convert("L"))


def _white_box(gray: np.ndarray) -> tuple[float, float, float, float]:
    rows, cols = np.nonzero(gray > 128)
    height, width = gray.shape
    return (
        cols.min() / width,
        rows.min() / height,
        (cols.max() + 1) / width,
        (rows.max() + 1) / height,
    )


@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_a_turned_box_lands_where_ffmpeg_turns_the_face(tmp_path: Path, rotation: int):
    turned = _ffmpeg(
        _picture(tmp_path / "face.png"), _get_rotation_filter(rotation), tmp_path / "turned.png"
    )

    (box,) = rotated_faces((_FACE,), rotation)

    seen = _white_box(turned)
    assert (box.x1, box.y1, box.x2, box.y2) == pytest.approx(seen, abs=0.01)
    assert (box.named, box.person_id) == (_FACE.named, _FACE.person_id)


@pytest.mark.parametrize("rotation", [None, 0])
def test_no_rotation_leaves_the_boxes_alone(rotation: int | None):
    assert rotated_faces((_FACE,), rotation) == (_FACE,)


def _encoder(detected: tuple[FaceBox, ...]) -> ClipEncoder:
    # WHY: the prober runs ffprobe on a video; the crop only needs the picture's size.
    prober = SimpleNamespace(get_video_resolution=lambda _path: (_SRC_W, _SRC_H))
    settings = AssemblySettings(
        encoding_plan=standalone_assembly_encoding_plan(23), scale_mode="smart_zoom"
    )
    # WHY: the detector decodes frames off disk; these tests hand it its answer.
    return ClipEncoder(settings, prober, lambda _path: detected)


def _target_against(rotation: int) -> tuple[int, int]:
    """A canvas of the other orientation than the turned picture, so the crop has to choose."""
    turned_is_portrait = rotation in (90, 270)
    return (320, 180) if turned_is_portrait else (180, 320)


def _framed(tmp_path: Path, clip: AssemblyClip, encoder: ClipEncoder, rotation: int) -> np.ndarray:
    target_w, target_h = _target_against(rotation)
    crop = encoder.smart_zoom_crop(clip, target_w, target_h)
    assert crop is not None
    # The order the encoder uses: turn the picture, then crop it.
    chain = f"{_get_rotation_filter(rotation)},{crop}"
    return _ffmpeg(clip.path, chain, tmp_path / "framed.png")


@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_the_crop_keeps_the_subject_immich_names_on_a_turned_clip(tmp_path: Path, rotation: int):
    clip = AssemblyClip(
        path=_picture(tmp_path / "face.png"),
        duration=3.0,
        rotation_override=rotation,
        known_faces=PictureFaces((_FACE,), frozenset({"kid"})),
    )

    framed = _framed(tmp_path, clip, _encoder(()), rotation)

    assert (framed > 128).any(), "the crop left the face out of the frame"


@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_the_crop_keeps_the_face_a_detector_found_on_a_turned_clip(tmp_path: Path, rotation: int):
    clip = AssemblyClip(
        path=_picture(tmp_path / "face.png"), duration=3.0, rotation_override=rotation
    )
    anonymous = FaceBox(_FACE.x1, _FACE.y1, _FACE.x2, _FACE.y2, named=False)

    framed = _framed(tmp_path, clip, _encoder((anonymous,)), rotation)

    assert (framed > 128).any(), "the crop left the face out of the frame"
