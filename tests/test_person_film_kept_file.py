"""A picture a person film chose stays in it when another file carries it (#2358).

A person film reads its window twice: the pictures Immich recognises the subject on, and the
whole window as context. When the recognised file is an original whose edit (or a stack's top
file) carries the picture, the carrying file arrives only with the context; the film must keep
the picture through that file instead of losing it, star included, without a word.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import create_autospec

from immich_memories.api.models import Asset, AssetType, ExifInfo, MetadataSearchResult, Person
from immich_memories.api.sync_client import SyncImmichClient
from immich_memories.timeperiod import DateRange
from tests.test_capture_local_time import cut

SUBJECT = Person(id="subject-face", name="Subject")
WINDOW = DateRange(datetime(2024, 5, 1), datetime(2024, 5, 31, 23, 59, 59))


def _file(key: str, taken: datetime, *, name: str, modified: datetime | None = None, **fields):
    return Asset(
        id=key,
        type=AssetType.IMAGE,
        fileCreatedAt=taken,
        fileModifiedAt=modified or taken,
        updatedAt=modified or taken,
        originalFileName=name,
        exifInfo=ExifInfo(make="Apple", model="iPhone 15 Pro"),
        width=4032,
        height=3024,
        **fields,
    )


def test_a_person_film_keeps_a_recognised_picture_through_its_edited_file(tmp_path):
    days = [
        _file(
            f"day-{n:02}",
            datetime(2024, 5, 2 + n, 12, tzinfo=UTC),
            name=f"IMG_{n:04}.HEIC",
            people=[SUBJECT],
        )
        for n in range(12)
    ]
    shot = datetime(2024, 5, 20, 17, tzinfo=UTC)
    # The camera's file, where Immich recognised the subject and the owner set the star.
    original = _file("original", shot, name="IMG_9000.HEIC", people=[SUBJECT], isFavorite=True)
    # The owner's later crop of the same shot: Immich found no face on it.
    edit = _file("edited", shot, name="IMG_9000.HEIC", modified=shot + timedelta(days=3))

    # WHY: the Immich read boundary (face boxes); the autospec refuses what the real one would.
    client = create_autospec(SyncImmichClient, instance=True)
    client.get_asset_faces.return_value = []
    client.get_server_info.return_value = SimpleNamespace(major=2, minor=0, version_string="2.0.0")
    client.search_metadata.return_value = MetadataSearchResult()

    chosen, _plan = cut(
        tmp_path,
        "person_spotlight",
        (WINDOW,),
        [*days, original],
        context_only=[edit],
        client=client,
    )

    assert "edited" in chosen


def test_a_stack_member_a_person_film_asked_for_is_played_by_the_stack_top():
    """The probe from #2358: the demand for a member names the stack's primary."""
    from immich_memories.analysis.editorial_source_route import metadata_demand
    from immich_memories.analysis.selection_source import (
        EditorialDependencies,
        EditorialSelectionRequest,
        SourceScope,
        prepare_editorial_source,
    )

    shot = datetime(2024, 5, 20, 17, tzinfo=UTC)
    original = _file("original", shot, name="IMG_9001.HEIC", people=[SUBJECT], isFavorite=True)
    top = _file("stack-top", shot + timedelta(seconds=2), name="IMG_9002.HEIC")
    prepared = prepare_editorial_source(
        EditorialSelectionRequest(SourceScope(min_source_short_side=0)),
        EditorialDependencies(
            source_fetcher=lambda _scope: (top, original),
            stack_of=lambda: {"original": "stack-top"},
        ),
    )

    rows = metadata_demand(prepared, [original], photo_seconds=4)

    assert [row.clip.asset.id for row in rows] == ["stack-top"]
    assert rows[0].clip.asset.is_favorite
