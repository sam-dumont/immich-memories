"""The wizard's pool holds the pictures a person's episode brings, and says which they are.

The owner reviews the pool before a cut and can untick anything. A picture that joins
only because the person was recognised elsewhere in its episode must be on that screen,
and marked, so the owner can tell it from one where the face itself was found.
"""

from datetime import timedelta
from unittest.mock import MagicMock, patch

from immich_memories.api.models import Asset, AssetType, Person
from immich_memories.timeperiod import calendar_year
from immich_memories.ui.pages import step2_loading
from immich_memories.ui.state import AppState

ADA = Person(id="face-ada", name="Ada")
WINDOW = calendar_year(2024)


def photo(key, *, hours, people=()):
    when = WINDOW.start + timedelta(hours=hours)
    return Asset(
        id=key,
        type=AssetType.IMAGE,
        fileCreatedAt=when,
        fileModifiedAt=when,
        updatedAt=when,
        people=list(people),
    )


def spotlight() -> AppState:
    return AppState(
        memory_type="person_spotlight",
        date_ranges=[WINDOW],
        memory_preset_params={"year": 2024},
        people=[ADA],
        selected_person=ADA,
    )


def test_the_pool_holds_the_episode_and_marks_what_the_episode_brought():
    face = photo("face", hours=9, people=[ADA])
    feeding = photo("feeding", hours=9.5)
    other_day = photo("other-day", hours=48)
    client = MagicMock()
    # WHY: Immich is the read boundary: the window's two unfiltered reads.
    client.get_photos_for_date_range.return_value = [face, feeding, other_day]
    client.get_videos_for_date_range.return_value = []
    state = spotlight()

    with patch.object(step2_loading, "SyncImmichClient") as factory:
        factory.return_value.__enter__.return_value = client
        pool = step2_loading._fetch_photos(state)

    assert [p.id for p in pool] == ["face", "feeding"]
    assert [state.found_by_episode(p) for p in pool] == [False, True]


def test_a_memory_about_nobody_marks_nothing():
    state = AppState(memory_type="monthly_highlights", date_ranges=[WINDOW])

    assert not state.found_by_episode(photo("anything", hours=9))
