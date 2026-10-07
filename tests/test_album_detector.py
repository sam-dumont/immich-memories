"""Album candidates (#2229)."""

from __future__ import annotations

from datetime import date

from immich_memories.automation.album_detector import AlbumDetector
from immich_memories.automation.candidates import CandidateCategory, make_memory_key

ME = "user-me"
TODAY = date(2026, 10, 7)


def _album(album_id: str = "a1", count: int = 25, *, owner: str = ME, shared: bool = False) -> dict:
    return {
        "id": album_id,
        "albumName": "Lisbon",
        "assetCount": count,
        "shared": shared,
        "startDate": "2025-05-01T09:00:00.000Z",
        "endDate": "2025-05-05T18:00:00.000Z",
        "albumUsers": [{"user": {"id": owner}, "role": "owner"}],
    }


def _film_key(album_id: str, count: int) -> str:
    return make_memory_key(
        "album", date(2025, 5, 1), date(2025, 5, 5), discriminator=f"{album_id}:{count}"
    )


def test_a_new_album_with_twenty_pictures_is_proposed():
    detection = AlbumDetector().detect([_album(count=25)], ME, set(), TODAY, include_shared=False)

    (candidate,) = detection.candidates
    assert candidate.category is CandidateCategory.ALBUM
    assert candidate.memory_type == "album"
    assert candidate.extra_params["album_id"] == "a1"
    assert candidate.asset_count == 25
    assert candidate.person_names == []


def test_an_album_under_twenty_pictures_is_left_alone():
    detection = AlbumDetector().detect([_album(count=19)], ME, set(), TODAY, include_shared=False)

    assert detection.candidates == []


def test_an_album_filmed_at_its_current_size_is_not_proposed_again():
    detection = AlbumDetector().detect(
        [_album(count=25)], ME, {_film_key("a1", 25)}, TODAY, include_shared=False
    )

    assert detection.candidates == []


def test_an_album_that_grew_by_thirty_and_half_again_is_a_new_candidate_with_a_new_key():
    keys = {_film_key("a1", 40)}

    grown = AlbumDetector().detect([_album(count=70)], ME, keys, TODAY, include_shared=False)
    barely = AlbumDetector().detect([_album(count=69)], ME, keys, TODAY, include_shared=False)

    assert [c.memory_key for c in grown.candidates] == [_film_key("a1", 70)]
    assert barely.candidates == []


def test_thirty_more_pictures_is_not_enough_when_the_album_was_already_big():
    keys = {_film_key("a1", 200)}

    detection = AlbumDetector().detect([_album(count=240)], ME, keys, TODAY, include_shared=False)

    assert detection.candidates == []


def test_an_album_someone_shared_with_you_needs_the_setting():
    shared = _album(owner="user-other", shared=True)

    default = AlbumDetector().detect([shared], ME, set(), TODAY, include_shared=False)
    opted_in = AlbumDetector().detect([shared], ME, set(), TODAY, include_shared=True)

    assert default.candidates == []
    assert len(opted_in.candidates) == 1


def test_an_album_you_own_and_share_is_still_yours():
    detection = AlbumDetector().detect(
        [_album(shared=True)], ME, set(), TODAY, include_shared=False
    )

    assert len(detection.candidates) == 1


def test_an_album_filmed_by_hand_counts_as_filmed():
    # `generate --from-album` records the album's own span and no id.
    by_hand = make_memory_key("album", date(2025, 5, 1), date(2025, 5, 5))

    detection = AlbumDetector().detect([_album()], ME, {by_hand}, TODAY, include_shared=False)

    assert detection.candidates == []


def test_an_album_without_dates_still_gets_a_window():
    undated = _album() | {"startDate": None, "endDate": None, "createdAt": "2026-09-01T10:00:00Z"}

    (candidate,) = (
        AlbumDetector().detect([undated], ME, set(), TODAY, include_shared=False).candidates
    )

    assert candidate.date_range_start == date(2026, 9, 1)


def test_an_album_spanning_more_than_a_year_is_a_collection_not_a_film():
    # A phone's "Recents" or "Favorites": seven years of every picture.
    catch_all = _album(count=7000) | {
        "startDate": "2019-09-23T00:00:00.000Z",
        "endDate": "2026-10-05T00:00:00.000Z",
    }

    detection = AlbumDetector().detect([catch_all], ME, set(), TODAY, include_shared=False)

    assert detection.candidates == []
    assert "1 album" in detection.notes[0] and "six months" in detection.notes[0]
