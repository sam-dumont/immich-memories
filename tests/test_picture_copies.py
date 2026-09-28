"""A picture forwarded back into the library under a new name is still one picture."""

from __future__ import annotations

from datetime import UTC, datetime

from immich_memories.analysis.picture_copies import picture_copies
from immich_memories.api.models import AssetType
from tests.conftest import make_asset

_SECOND = datetime(2024, 2, 16, 13, 41, 3, tzinfo=UTC)


def _photo(asset_id: str, name: str, *, width: int, height: int, micro: int = 0):
    photo = make_asset(
        asset_id, file_created_at=_SECOND.replace(microsecond=micro), original_file_name=name
    )
    photo.type = AssetType.IMAGE
    photo.width, photo.height = width, height
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
