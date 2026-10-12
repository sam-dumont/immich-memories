"""A move over a picture ends on the person the memory is about, with every face it can hold.

Issue #2440: a people memory zoomed to the largest face in a picture, whoever it
belonged to, and could push the other faces out of the frame. The face data
here is invented; boxes are in the pixels of the rendition Immich detected on.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from immich_memories.analysis.framing_target import (
    PictureFaces,
    framing_centre,
    picture_faces,
)
from immich_memories.analysis.subject_framing import FaceBox
from immich_memories.api.models import Asset, AssetFace, AssetType, Person

# A 1000x500 thumbnail: x and y normalise by different sizes.
_REF_W, _REF_H = 1000, 500


def _face(face_id: str, left: int, top: int, size: int) -> AssetFace:
    return AssetFace(
        id=face_id,
        boundingBoxX1=left,
        boundingBoxY1=top,
        boundingBoxX2=left + size,
        boundingBoxY2=top + size,
        imageWidth=_REF_W,
        imageHeight=_REF_H,
    )


def _photo(*people: Person, asset_id: str = "group-photo") -> Asset:
    now = datetime(2024, 1, 1, tzinfo=UTC)
    return Asset(
        id=asset_id,
        type=AssetType.IMAGE,
        fileCreatedAt=now,
        fileModifiedAt=now,
        updatedAt=now,
        people=list(people),
    )


def _box(x1: float, y1: float, x2: float, y2: float, person_id: str | None = None) -> FaceBox:
    return FaceBox(x1, y1, x2, y2, named=person_id is not None, person_id=person_id)


def _window_around(centre: tuple[float, float], window: tuple[float, float]):
    return (
        centre[0] - window[0] / 2,
        centre[1] - window[1] / 2,
        centre[0] + window[0] / 2,
        centre[1] + window[1] / 2,
    )


def _inside(box: FaceBox, frame: tuple[float, float, float, float]) -> bool:
    eps = 1e-6
    return (
        box.x1 >= frame[0] - eps
        and box.y1 >= frame[1] - eps
        and box.x2 <= frame[2] + eps
        and box.y2 <= frame[3] + eps
    )


# ---- the framing rule --------------------------------------------------------


class TestFramingCentre:
    def test_no_faces_frames_the_centre(self):
        assert framing_centre((), frozenset(), (0.6, 0.6)) == (0.5, 0.5)

    def test_the_subject_wins_over_a_larger_face(self):
        subject = _box(0.05, 0.40, 0.12, 0.50, "kid")
        stranger = _box(0.75, 0.30, 0.95, 0.60, "stranger")
        window = (0.5, 0.5)

        centre = framing_centre((subject, stranger), frozenset({"kid"}), window)

        assert _inside(subject, _window_around(centre, window))
        assert not _inside(stranger, _window_around(centre, window))

    def test_two_subjects_are_framed_together(self):
        first = _box(0.10, 0.40, 0.18, 0.50, "a")
        second = _box(0.50, 0.42, 0.58, 0.52, "b")
        bystander = _box(0.85, 0.10, 0.99, 0.35, "c")
        window = (0.55, 0.55)

        centre = framing_centre((first, second, bystander), frozenset({"a", "b"}), window)

        frame = _window_around(centre, window)
        assert _inside(first, frame)
        assert _inside(second, frame)

    def test_a_group_that_fits_stays_whole(self):
        faces = (
            _box(0.20, 0.30, 0.28, 0.40, "kid"),
            _box(0.45, 0.32, 0.60, 0.50, "dad"),
            _box(0.62, 0.35, 0.70, 0.45, "mum"),
        )
        window = (0.6, 0.6)

        centre = framing_centre(faces, frozenset({"kid"}), window)

        frame = _window_around(centre, window)
        assert all(_inside(face, frame) for face in faces)

    def test_a_group_that_cannot_fit_keeps_the_subject(self):
        subject = _box(0.02, 0.40, 0.10, 0.50, "kid")
        far_right = _box(0.88, 0.40, 0.98, 0.52, "aunt")
        window = (0.6, 0.6)

        centre = framing_centre((subject, far_right), frozenset({"kid"}), window)

        assert _inside(subject, _window_around(centre, window))

    def test_without_a_subject_the_largest_face_leads_and_the_rest_are_kept(self):
        small = _box(0.30, 0.40, 0.36, 0.48)
        largest = _box(0.60, 0.30, 0.75, 0.55)
        window = (0.6, 0.6)

        centre = framing_centre((small, largest), frozenset(), window)

        frame = _window_around(centre, window)
        assert _inside(largest, frame)
        assert _inside(small, frame)

    def test_without_a_subject_an_unfittable_group_keeps_the_largest(self):
        small = _box(0.02, 0.40, 0.08, 0.48)
        largest = _box(0.80, 0.30, 0.97, 0.55)
        window = (0.5, 0.5)

        centre = framing_centre((small, largest), frozenset(), window)

        assert _inside(largest, _window_around(centre, window))

    def test_the_window_never_leaves_the_picture(self):
        corner = _box(0.0, 0.0, 0.05, 0.05)
        window = (0.6, 0.4)

        x, y = framing_centre((corner,), frozenset(), window)

        assert (x, y) == pytest.approx((0.3, 0.2))


# ---- the subject, read off Immich's data -----------------------------------------


class TestPictureFaces:
    def test_boxes_normalise_by_the_rendition_immich_detected_on(self):
        person = Person(id="kid", name="Kid", faces=[_face("f1", 500, 250, 100)])

        faces = picture_faces(_photo(person), ())

        [box] = faces.faces
        assert (box.x1, box.y1, box.x2, box.y2) == pytest.approx((0.5, 0.5, 0.6, 0.7))
        assert box.person_id == "kid"

    def test_the_subject_matches_by_name_or_by_id(self):
        kid = Person(id="kid-id", name="  Little  Kid ", faces=[_face("f1", 10, 10, 50)])
        dad = Person(id="dad-id", name="Dad", faces=[_face("f2", 600, 10, 200)])

        by_name = picture_faces(_photo(kid, dad), ("little kid",))
        by_id = picture_faces(_photo(kid, dad), ("dad-id", None))

        assert by_name.subject_ids == frozenset({"kid-id"})
        assert by_id.subject_ids == frozenset({"dad-id"})

    def test_a_memory_about_nobody_has_no_subject(self):
        kid = Person(id="kid-id", name="Kid", faces=[_face("f1", 10, 10, 50)])

        assert picture_faces(_photo(kid), ()).subject_ids == frozenset()


# ---- videos: the smart-zoom crop ------------------------------------------------


def _clip_with(faces: PictureFaces):
    from immich_memories.processing.assembly_config import AssemblyClip

    return AssemblyClip(path=Path("clip.mp4"), duration=3.0, asset_id="clip", known_faces=faces)


def _encoder(detected: tuple[FaceBox, ...]):
    from immich_memories.processing.assembly_config import (
        AssemblySettings,
        standalone_assembly_encoding_plan,
    )
    from immich_memories.processing.clip_encoder import ClipEncoder

    # WHY: the prober reads the clip file with ffprobe; the crop only needs its size.
    prober = SimpleNamespace(get_video_resolution=lambda _path: (1920, 1080))
    settings = AssemblySettings(
        encoding_plan=standalone_assembly_encoding_plan(23), scale_mode="smart_zoom"
    )
    # WHY: the detector decodes frames off disk; these tests hand it its answer.
    return ClipEncoder(settings, prober, lambda _path: detected)


def _crop_x(filter_text: str) -> int:
    crop = filter_text.split("crop=")[1].split(",")[0]
    return int(crop.split(":")[2])


class TestSmartZoomCrop:
    def test_the_crop_follows_the_subject_immich_names(self):
        subject = _box(0.05, 0.40, 0.10, 0.50, "kid")
        stranger = _box(0.80, 0.30, 0.95, 0.60, "x")
        clip = _clip_with(PictureFaces((subject, stranger), frozenset({"kid"})))
        # The anonymous detector would see only the big stranger.
        encoder = _encoder((_box(0.80, 0.30, 0.95, 0.60),))

        crop = encoder.smart_zoom_crop(clip, 1080, 1920)

        assert crop is not None
        assert _crop_x(crop) <= 5

    def test_without_a_subject_the_detector_decides(self):
        clip = _clip_with(PictureFaces((_box(0.05, 0.40, 0.10, 0.50, "kid"),), frozenset()))
        encoder = _encoder((_box(0.80, 0.30, 0.95, 0.60),))

        crop = encoder.smart_zoom_crop(clip, 1080, 1920)

        assert crop is not None
        assert _crop_x(crop) >= 1920 - 607 - 5

    def test_no_face_anywhere_means_no_crop(self):
        assert _encoder(()).smart_zoom_crop(_clip_with(PictureFaces()), 1080, 1920) is None


# ---- the memory's people reach the renderers ------------------------------------


def _people_film(tmp_path: Path, clip) -> object:
    from unittest.mock import MagicMock

    from immich_memories.config_loader import Config
    from immich_memories.generate import GenerationParams

    return GenerationParams(
        clips=[clip],
        output_path=tmp_path / "memory.mp4",
        config=Config(),
        client=MagicMock(),
        clip_segments={clip.asset.id: (0.0, 3.0)},
        person_name="Kid",
        memory_people=("kid", "dad"),
    )


def test_a_people_film_hands_its_people_to_the_photo_renderer(tmp_path: Path, monkeypatch):
    from unittest.mock import MagicMock

    from immich_memories.generate_clips import extract_clips
    from tests.conftest import make_clip

    clip = make_clip("still", duration=3.0)
    clip.asset.type = AssetType.IMAGE
    # WHY: the encode writes a file; the subjects it is handed are what is under test.
    render = MagicMock(return_value=None)
    monkeypatch.setattr("immich_memories.photos.photo_pipeline.render_single_photo", render)
    monkeypatch.setattr(
        "immich_memories.generate_photos.detect_photo_resolution", lambda *_: (1920, 1080)
    )

    extract_clips(_people_film(tmp_path, clip), None, tmp_path)

    assert {"kid", "dad"} <= set(render.call_args.kwargs["subjects"])


def test_a_people_film_marks_its_subject_on_each_video_clip(tmp_path: Path, monkeypatch):
    from immich_memories.generate_clips import extract_clips
    from tests.conftest import make_clip

    clip = make_clip("video", duration=3.0)
    clip.asset.people = [
        Person(id="kid-id", name="Kid", faces=[_face("f1", 40, 200, 60)]),
        Person(id="x", name="Stranger", faces=[_face("f2", 750, 100, 220)]),
    ]
    local = tmp_path / "source.mp4"
    local.write_bytes(b"video")
    clip.local_path = str(local)
    segment = tmp_path / "segment.mp4"
    segment.write_bytes(b"segment")
    # WHY: extraction and probing run FFmpeg; the clip's framing data is what is under test.
    monkeypatch.setattr(
        "immich_memories.processing.clips.extract_clip", lambda *_args, **_kwargs: segment
    )
    monkeypatch.setattr(
        "immich_memories.generate_clips.probe_file_duration", lambda _path, **_kwargs: 3.0
    )

    [assembled] = extract_clips(_people_film(tmp_path, clip), None, tmp_path)

    assert assembled.known_faces.subject_ids == frozenset({"kid-id"})
    assert len(assembled.known_faces.faces) == 2


def _face_row(person: Person | None) -> AssetFace:
    face = _face("f9", 40, 200, 60)
    return face.model_copy(update={"person": person})


def test_a_still_fetches_its_face_boxes_before_it_moves(tmp_path: Path, monkeypatch):
    """Immich's asset endpoints name people without geometry; the boxes have their own."""
    from unittest.mock import MagicMock

    from immich_memories.generate_clips import extract_clips
    from tests.conftest import make_clip
    from tests.immich_fakes import fake_immich_client

    clip = make_clip("still", duration=3.0)
    clip.asset.type = AssetType.IMAGE
    clip.asset.people = [Person(id="kid-id", name="Kid")]
    params = _people_film(tmp_path, clip)
    params.client = fake_immich_client()
    params.client.get_asset_faces.return_value = [_face_row(Person(id="kid-id", name="Kid"))]
    # WHY: the encode writes a file; the asset it is handed is what is under test.
    render = MagicMock(return_value=None)
    monkeypatch.setattr("immich_memories.photos.photo_pipeline.render_single_photo", render)
    monkeypatch.setattr(
        "immich_memories.generate_photos.detect_photo_resolution", lambda *_: (1920, 1080)
    )

    extract_clips(params, None, tmp_path)

    rendered = render.call_args.kwargs["asset"]
    faces = picture_faces(rendered, render.call_args.kwargs["subjects"])
    assert faces.subject_ids == frozenset({"kid-id"})
    params.client.get_asset_faces.assert_called_once_with(clip.asset.id)


def test_a_failed_face_read_leaves_the_still_without_faces():
    from immich_memories.api.immich import ImmichAPIError
    from immich_memories.generate_photos import with_face_boxes
    from tests.immich_fakes import fake_immich_client

    client = fake_immich_client()
    client.get_asset_faces.side_effect = ImmichAPIError("down")
    asset = _photo(Person(id="kid-id", name="Kid"))

    assert with_face_boxes(asset, client) is asset
    assert with_face_boxes(asset, None) is asset


def test_a_routed_face_read_that_fails_keeps_the_still_in_the_film(tmp_path: Path, monkeypatch):
    """With a second account, a failed face read comes back as AccountReadFailed (#2448).

    The boxes only steer the move, so the still renders without them and stays in the film.
    """
    from unittest.mock import MagicMock

    from immich_memories.api.access_clients import AccessBoundClient, AccountReadFailed
    from immich_memories.generate_clips import extract_clips
    from tests.conftest import make_clip
    from tests.immich_fakes import fake_immich_client

    clip = make_clip("still", duration=3.0)
    clip.asset.type = AssetType.IMAGE
    params = _people_film(tmp_path, clip)
    params.client = fake_immich_client(AccessBoundClient)
    params.client.get_asset_faces.side_effect = AccountReadFailed("account 'partner' refused")
    # WHY: the encode writes a file; whether the still is rendered at all is under test.
    render = MagicMock(return_value=None)
    monkeypatch.setattr("immich_memories.photos.photo_pipeline.render_single_photo", render)
    monkeypatch.setattr(
        "immich_memories.generate_photos.detect_photo_resolution", lambda *_: (1920, 1080)
    )

    extract_clips(params, None, tmp_path)

    render.assert_called_once()
    assert render.call_args.kwargs["asset"].faces == []
