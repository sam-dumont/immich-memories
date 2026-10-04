"""A multi-person memory is about the people recognised together, on the same picture.

Naming two people asks for the pictures that hold both of their faces directly, strictly
per picture (#1954), never widened to the episode around them. This is not two solo
reels unioned either: AND asks for one picture that carries both. These tests pin that
rule at the fetch seam the CLI uses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from immich_memories.api.models import Person
from immich_memories.cli._asset_fetch import fetch_photos, fetch_videos
from immich_memories.timeperiod import DateRange

PERSON_A = "person-a"
PERSON_B = "person-b"

WINDOW = DateRange(start=datetime(2025, 1, 1), end=datetime(2025, 12, 31, 23, 59, 59))
MORNING = datetime(2025, 6, 1, 9, 0, 0)
EVENING = datetime(2025, 6, 1, 20, 0, 0)


@dataclass
class _Asset:
    id: str
    faces: set[str] = field(default_factory=set)
    file_created_at: datetime = MORNING
    duration_seconds: float = 8.0
    exif_info: None = None

    @property
    def people(self) -> list[Person]:
        return [Person(id=face) for face in sorted(self.faces)]


class _LibraryClient:
    """The two unfiltered window reads the Immich client makes for a people fetch.

    WHY: Immich is the read boundary; per-person endpoints are left undefined, so a
    fetch that still asks Immich per frame fails here.
    """

    def __init__(self, videos: list[_Asset], photos: list[_Asset] | None = None) -> None:
        self._videos = videos
        self._photos = photos or []

    def get_photos_for_date_range(
        self, date_range: DateRange, progress_callback=None, **people
    ) -> list[_Asset]:  # noqa: ARG002
        assert not any(people.values()), "a per-person photo read"
        return list(self._photos)

    def get_videos_for_date_range(self, date_range: DateRange) -> list[_Asset]:  # noqa: ARG002
        return list(self._videos)


class _SilentProgress:
    def add_task(self, *_args, **_kwargs) -> int:
        return 0

    def update(self, *_args, **_kwargs) -> None:
        return None


def _fetch(
    client: _LibraryClient,
    person_ids: list[str],
    *,
    person_match: str = "and",
) -> list[_Asset]:
    return fetch_videos(
        client=client,
        progress=_SilentProgress(),
        date_ranges=[WINDOW],
        person_ids=person_ids,
        person_match=person_match,
    )


def test_two_people_need_both_faces_on_the_same_picture():
    client = _LibraryClient(
        [
            _Asset("a-alone", {PERSON_A}),
            _Asset("b-alone", {PERSON_B}, file_created_at=MORNING + timedelta(minutes=20)),
            _Asset("nobody", file_created_at=MORNING + timedelta(minutes=40)),
            _Asset(
                "a-and-b", {PERSON_A, PERSON_B}, file_created_at=MORNING + timedelta(minutes=50)
            ),
            _Asset("a-evening", {PERSON_A}, file_created_at=EVENING),
        ]
    )

    assets = _fetch(client, [PERSON_A, PERSON_B])

    assert [a.id for a in assets] == ["a-and-b"]


def test_people_never_sharing_a_frame_yield_nothing_rather_than_two_solo_reels():
    client = _LibraryClient(
        [
            _Asset("a-alone", {PERSON_A}),
            _Asset("b-alone", {PERSON_B}, file_created_at=EVENING),
        ]
    )

    assert _fetch(client, [PERSON_A, PERSON_B]) == []


def test_or_selects_each_persons_own_pictures():
    client = _LibraryClient(
        [
            _Asset("a-alone", {PERSON_A}),
            _Asset("a-and-b", {PERSON_A, PERSON_B}, file_created_at=MORNING + timedelta(minutes=5)),
            _Asset("b-evening", {PERSON_B}, file_created_at=EVENING),
            _Asset("nobody-next-day", file_created_at=EVENING + timedelta(days=1)),
        ]
    )

    assets = _fetch(client, [PERSON_A, PERSON_B], person_match="or")

    assert [asset.id for asset in assets] == ["a-alone", "a-and-b", "b-evening"]


def test_photos_follow_the_same_per_picture_rule_as_videos():
    client = _LibraryClient(
        [_Asset("video-b", {PERSON_B}, file_created_at=MORNING + timedelta(minutes=10))],
        photos=[
            _Asset("photo-a-and-b", {PERSON_A, PERSON_B}),
            _Asset("photo-nobody-named", file_created_at=MORNING + timedelta(minutes=30)),
            _Asset("photo-a-evening", {PERSON_A}, file_created_at=EVENING),
        ],
    )

    photos = fetch_photos(client=client, date_ranges=[WINDOW], person_ids=[PERSON_A, PERSON_B])

    assert [p.id for p in photos] == ["photo-a-and-b"]


def test_one_person_selects_only_the_pictures_their_own_face_is_on():
    client = _LibraryClient(
        [
            _Asset("a-alone", {PERSON_A}),
            _Asset("unrecognised", file_created_at=MORNING + timedelta(minutes=15)),
            _Asset("b-evening", {PERSON_B}, file_created_at=EVENING),
        ]
    )

    assets = _fetch(client, [PERSON_A])

    assert {a.id for a in assets} == {"a-alone"}
