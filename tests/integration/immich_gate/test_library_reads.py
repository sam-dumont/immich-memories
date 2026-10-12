"""Real-Immich gate: the product reads a seeded library whole, on v2 and v3.

Expectations come from the fixture script (tests/e2e/fake_library.py), never
from what the server happened to answer last time.
"""

from __future__ import annotations

import pytest

from immich_memories.api.models import AssetType
from tests.e2e.fake_library import CAST, LIBRARY, STORIES, YEAR, carriers_of
from tests.integration.immich_fixtures import requires_immich
from tests.integration.immich_gate.conftest import BULK_YEAR, FIXTURE_MONTH
from tests.integration.immich_gate.media import BULK_ALBUM, BULK_COUNT, CAMERA

pytestmark = [requires_immich]

_VIDEOS = sorted(picture.filename for picture in LIBRARY if picture.is_video)
_STILLS = sorted(picture.filename for picture in LIBRARY if not picture.is_video)


def test_connects_and_speaks_the_major_it_was_started_on(gate_client, gate_version):
    assert gate_client.validate_connection()
    major, minor = {"v2": (2, 7), "v32": (3, 2), "v3": (3, 3)}[gate_version]
    version = gate_client.get_server_info()
    assert (version.major, version.minor) == (major, minor)
    assert gate_client.get_api_version().value == f"v{major}"
    if gate_version == "v3":
        assert version.patch == 0 and version.prerelease is None


def test_the_fixture_month_reads_every_video_and_still(gate_client):
    videos = gate_client.get_videos_for_date_range(FIXTURE_MONTH)
    stills = gate_client.get_photos_for_date_range(FIXTURE_MONTH)

    assert sorted(asset.original_file_name for asset in videos) == _VIDEOS
    assert sorted(asset.original_file_name for asset in stills) == _STILLS


def test_a_still_carries_its_camera_and_its_own_place_and_a_clip_without_one_none(gate_client):
    placed = next(p for p in LIBRARY if not p.is_video and p.place is not None and p.shipped)
    clip = next(p for p in LIBRARY if p.is_video)
    assert clip.place is None, "the fixture's clips hold no GPS of their own"
    videos = {a.original_file_name: a for a in gate_client.get_videos_for_date_range(FIXTURE_MONTH)}
    stills = gate_client.get_photos_for_date_range(FIXTURE_MONTH)
    by_name = {a.original_file_name: a for a in stills}

    still = gate_client.get_asset(by_name[placed.filename].id)
    assert still.exif_info is not None
    assert still.exif_info.latitude == pytest.approx(placed.place.latitude, abs=1e-3)
    assert still.exif_info.longitude == pytest.approx(placed.place.longitude, abs=1e-3)
    video = gate_client.get_asset(videos[clip.filename].id)
    assert video.exif_info is None or video.exif_info.latitude is None
    assert {(s.exif_info.make, s.exif_info.model) for s in stills if s.exif_info} == {CAMERA}


def test_a_year_longer_than_one_search_page_reads_whole(gate_client):
    stills = gate_client.get_photos_for_date_range(BULK_YEAR)

    assert len({asset.id for asset in stills}) == BULK_COUNT


def test_an_album_longer_than_one_search_page_reads_whole(gate_client):
    album = gate_client.resolve_album(BULK_ALBUM)
    assets = gate_client.get_assets_for_album(album.id, asset_type=AssetType.IMAGE)

    assert album.asset_count == BULK_COUNT
    assert len({asset.id for asset in assets}) == BULK_COUNT


def test_people_tagged_by_hand_scope_the_videos_they_are_in(gate_client):
    assert set(CAST) <= {person.name for person in gate_client.get_all_people()}
    for name in CAST:
        person = gate_client.get_person_by_name(name)
        assert person is not None, name
        videos = gate_client.get_videos_for_person_and_date_range(person.id, FIXTURE_MONTH)
        expected = sorted(p.filename for p in LIBRARY if p.is_video and name in p.people)
        assert sorted(asset.original_file_name for asset in videos) == expected, name


def test_story_albums_resolve_by_name_with_their_pictures(gate_client):
    listed = {album.name: album for album in gate_client.list_albums()}
    for story in STORIES:
        carriers = carriers_of(story.key)
        if not carriers:
            continue
        album = gate_client.resolve_album(story.title)
        assert album.asset_count == len(carriers), story.title
        assert listed[story.title].id == album.id
        assert album.start is not None
        assert album.start.year == YEAR
