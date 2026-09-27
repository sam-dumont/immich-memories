"""The people a memory names are looked up per episode, not per frame, from the first read.

Two people who spent the afternoon together but never stood in one frame used to give
"No videos or photos found": Immich was asked for frames holding both. The fetch now
reads the window once and keeps every picture of an episode the condition holds in.
"""

from datetime import UTC, datetime, timedelta

from immich_memories.api.models import AssetType, Person
from immich_memories.api.person_expression import PersonExpression
from immich_memories.api.person_scope import people_in_window, photos_in_window, videos_in_window
from immich_memories.timeperiod import DateRange
from tests.conftest import make_asset

WINDOW = DateRange(datetime(2024, 5, 4, tzinfo=UTC), datetime(2024, 5, 4, 23, 59, tzinfo=UTC))


def picture(key, *, hour, minute=0, faces=(), video=False):
    asset = make_asset(key, file_created_at=WINDOW.start + timedelta(hours=hour, minutes=minute))
    asset.type = AssetType.VIDEO if video else AssetType.IMAGE
    asset.people = [Person(id=face, name=f"Name of {face}") for face in faces]
    return asset


class Library:
    """Immich's two unfiltered window reads, counted.

    WHY: Immich is the read boundary; a real server is the integration tier's job.
    Any per-person endpoint is left undefined so a call to one fails the test.
    """

    def __init__(self, assets):
        self.assets = assets
        self.reads: list[str] = []

    def get_videos_for_date_range(self, _window):
        self.reads.append("videos")
        return [a for a in self.assets if a.type == AssetType.VIDEO]

    def get_photos_for_date_range(self, _window, progress_callback=None, **people):
        assert not any(people.values()), "a per-person photo read"
        self.reads.append("photos")
        return [a for a in self.assets if a.type == AssetType.IMAGE]


AFTERNOON = [
    picture("a-video", hour=14, faces=("face-a",), video=True),
    picture("b-photo", hour=14, minute=30, faces=("face-b",)),
    picture("unrecognised-video", hour=14, minute=45, video=True),
    picture("unrecognised-photo", hour=15),
]
EVENING_A_ALONE = [
    picture("a-evening", hour=20, faces=("face-a",)),
    picture("evening-unrecognised", hour=20, minute=5, video=True),
]


def test_and_finds_people_who_share_an_episode_but_never_a_frame():
    library = Library([*AFTERNOON, *EVENING_A_ALONE])

    videos = videos_in_window(library, ["face-a", "face-b"], WINDOW, person_match="and")
    photos = photos_in_window(library, ["face-a", "face-b"], WINDOW, person_match="and")

    assert [v.id for v in videos] == ["a-video", "unrecognised-video"]
    assert [p.id for p in photos] == ["b-photo", "unrecognised-photo"]


def test_one_window_costs_two_reads_however_many_people_it_names():
    library = Library([*AFTERNOON, *EVENING_A_ALONE])
    condition = PersonExpression.parse('("face-a" OR "face-c") AND ("face-b" OR "face-d")')

    videos, photos = people_in_window(library, WINDOW, condition)

    assert library.reads == ["videos", "photos"]
    assert {a.id for a in (*videos, *photos)} == {a.id for a in AFTERNOON}


def test_one_person_brings_the_unrecognised_pictures_of_their_episodes_only():
    library = Library([*AFTERNOON, *EVENING_A_ALONE])

    photos = photos_in_window(library, ["face-b"], WINDOW)

    assert [p.id for p in photos] == ["b-photo", "unrecognised-photo"]
