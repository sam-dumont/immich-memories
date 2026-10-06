"""A picture forwarded back into the library under a new name is still one picture."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from immich_memories.analysis.picture_copies import group_members, picture_copies, starred_keepers
from immich_memories.api.models import AssetType
from tests.conftest import make_asset

_SECOND = datetime(2024, 2, 16, 13, 41, 3, tzinfo=UTC)


def _photo(
    asset_id: str,
    name: str,
    *,
    width: int,
    height: int,
    micro: int = 0,
    file_modified_at: datetime | None = None,
    is_favorite: bool = False,
    model: str | None = "iPhone 15 Pro",
):
    photo = make_asset(
        asset_id,
        file_created_at=_SECOND.replace(microsecond=micro),
        original_file_name=name,
        is_favorite=is_favorite,
        exif_model=model,
    )
    photo.type = AssetType.IMAGE
    photo.width, photo.height = width, height
    if file_modified_at is not None:
        photo.file_modified_at = file_modified_at
    return photo


def test_a_forwarded_copy_under_a_uuid_name_folds_into_the_picture_by_its_pixels():
    # Measured on one February: 13 forwarded copies, every one 0 or 1 bit from its camera file
    # in the same second; the two different photos sharing a second sat 14 bits or more apart.
    album = _photo("album", "IMG_5640.JPG", width=1540, height=2048, micro=820000)
    forwarded = _photo(
        "forwarded", "bb16b1a2-b8e6-48f3-aae3-0c3d2a1f9e10.jpg", width=3008, height=4000
    )
    hashes = {"album": "c787b79981c3c7c7", "forwarded": "c787b79981c3c7c6"}

    copies = picture_copies([album, forwarded], hash_of=lambda asset: hashes[asset.id])

    # The forwarded file is the bigger one here, so it carries the picture.
    assert {key: keeper.id for key, keeper in copies.items()} == {"album": "forwarded"}


def test_burst_frames_that_hash_alike_stay_two_pictures():
    # 123 same-second pairs of camera-named frames hashed 0 bits apart: an 8x8 hash cannot
    # tell two frames of a burst apart, so without a forwarded name nothing folds.
    first = _photo("first", "IMG_5639.JPG", width=1540, height=2048)
    second = _photo("second", "IMG_5640.JPG", width=1540, height=2048)

    assert picture_copies([first, second], hash_of=lambda _asset: "c787b79981c3c7c7") == {}


def test_a_received_batch_of_different_photos_in_one_second_stays_apart():
    left = _photo("left", "4d4a6872-c7d5-4a25-a0c9-7b1e2f3a4b5c.jpg", width=1536, height=2048)
    right = _photo("right", "IMG_5293.HEIC", width=3024, height=4032)
    hashes = {"left": "ffffffff00000000", "right": "ffff0000ffff0000"}

    assert picture_copies([left, right], hash_of=lambda asset: hashes[asset.id]) == {}


def test_without_a_preview_a_forwarded_file_is_never_assumed_to_be_a_copy():
    album = _photo("album", "IMG_5640.JPG", width=1540, height=2048)
    forwarded = _photo(
        "forwarded", "bb16b1a2-b8e6-48f3-aae3-0c3d2a1f9e10.jpg", width=3008, height=4000
    )

    assert picture_copies([album, forwarded], hash_of=lambda _asset: None) == {}


def test_a_crop_edit_uploaded_later_keeps_the_edit_and_moves_the_star_to_it():
    # iOS re-uploads an edited render as a new file, same name and capture second, fewer
    # pixels after a crop; the old asset stays with no replace endpoint on the server.
    original = _photo(
        "original",
        "IMG_8153.HEIC",
        width=4284,
        height=5712,
        file_modified_at=_SECOND,
        is_favorite=True,
    )
    edited = _photo(
        "edited",
        "img_8153.heic",
        width=3762,
        height=5016,
        file_modified_at=_SECOND + timedelta(days=1),
    )

    copies = picture_copies([original, edited])

    assert {key: keeper.id for key, keeper in copies.items()} == {"original": "edited"}
    assert starred_keepers(copies, [original, edited]) == {"edited"}


def test_an_equal_size_edit_keeps_the_newest_file_not_the_largest_id():
    # Lowercase vs uppercase extension is iOS's own tell for an adjusted render, but the fold
    # must not depend on it: same stem case-insensitively, same model, same capture instant.
    # Equal pixels used to tie-break on the bigger asset id, which could keep either file.
    old = _photo("z-old", "IMG_8882.HEIC", width=4032, height=3024, file_modified_at=_SECOND)
    new = _photo(
        "a-new",
        "img_8882.heic",
        width=4032,
        height=3024,
        file_modified_at=_SECOND + timedelta(days=7),
    )

    copies = picture_copies([old, new])

    assert {key: keeper.id for key, keeper in copies.items()} == {"z-old": "a-new"}


def test_a_shared_album_downscale_still_loses_to_the_full_original():
    # Pixel ratio under 0.5 marks a shared-album copy, not an edit -- it never wins on
    # recency, only the full-size file does, even if it is the older upload.
    original = _photo("original", "IMG_6000.JPG", width=3024, height=4032, file_modified_at=_SECOND)
    shared_album = _photo(
        "shared",
        "IMG_6000.JPG",
        width=1024,
        height=1365,
        file_modified_at=_SECOND + timedelta(days=30),
    )

    copies = picture_copies([original, shared_album])

    assert {key: keeper.id for key, keeper in copies.items()} == {"shared": "original"}


def test_a_different_camera_model_at_the_same_name_and_instant_is_not_folded():
    # The fallback signal is stem + camera model + capture instant together; a name and an
    # instant without a matching model must not be assumed to be the same picture.
    one = _photo("one", "IMG_7000.JPG", width=3024, height=4032, model="iPhone 15 Pro")
    other = _photo("other", "IMG_7000.JPG", width=3024, height=4032, model="iPhone 11")

    assert picture_copies([one, other]) == {}


def test_group_members_maps_every_file_of_a_picture_to_the_whole_group():
    original = _photo("original", "IMG_1.JPG", width=3024, height=4032, file_modified_at=_SECOND)
    edited = _photo(
        "edited", "img_1.jpg", width=3024, height=4032, file_modified_at=_SECOND + timedelta(days=1)
    )

    copies = picture_copies([original, edited])
    groups = group_members(copies)

    assert groups["original"] == frozenset({"original", "edited"})
    assert groups["edited"] == frozenset({"original", "edited"})
