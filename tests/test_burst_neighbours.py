"""A person memory takes the whole burst its person is recognised in, and asks for no more."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from immich_memories.api.models import Person
from tests.conftest import make_asset

NOON = datetime(2025, 6, 1, 12, 0, tzinfo=UTC)


def _live(index: int, *, seconds: float = 0.0):
    asset = make_asset(
        f"still-{index}", file_created_at=NOON + timedelta(seconds=seconds), duration=None
    )
    asset.live_photo_video_id = f"video-{index}"
    return asset


class TestThePersonFetchReadsTheEpisode:
    """The person's episode is the source boundary, not the one frame their face was found in."""

    def test_a_person_fetch_keeps_the_burst_frames_their_face_was_not_found_in(self):
        from immich_memories.cli._asset_fetch import fetch_photos

        burst = [_live(index, seconds=index * 2.0) for index in range(3)]
        burst[1].people = [Person(id="person-1")]
        client = MagicMock()
        # WHY: the Immich server; the window read returns the whole burst.
        client.get_photos_for_date_range.return_value = burst
        client.get_videos_for_date_range.return_value = []

        found = fetch_photos(
            client=client,
            date_ranges=[MagicMock()],
            person_ids=["person-1"],
        )

        assert [asset.id for asset in found] == ["still-0", "still-1", "still-2"]
        client.get_live_photos_for_date_range.assert_not_called()

    def test_an_unfiltered_fetch_asks_for_nothing_extra(self):
        """With no person filter the window already holds every frame."""
        from immich_memories.cli._asset_fetch import fetch_photos

        burst = [_live(index, seconds=index * 2.0) for index in range(3)]
        client = MagicMock()
        client.get_photos_for_date_range.return_value = burst

        found = fetch_photos(client=client, date_ranges=[MagicMock()], person_ids=[])

        assert {a.id for a in found} == {"still-0", "still-1", "still-2"}
        client.get_live_photos_for_date_range.assert_not_called()
