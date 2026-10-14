"""In a film of several occurrences (a holiday, on this day, a birthday's earlier years), a
story stays inside one occurrence.

A holiday film's rules reader named a story "Days at home, 15 August – 15 August": 15 August
2004 and 15 August 2022, one story. The 2022 episode held no picture the editor could select,
so it carried no day, and the run grouping put a day-less episode beside whichever day sorted
next to it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from immich_memories.analysis.editorial_rule_reader import RuleStructureReader
from immich_memories.config_models_automation import TripsConfig
from immich_memories.config_models_editorial import EditorialPeopleConfig
from immich_memories.timeperiod import DateRange
from tests.picture_fake import PictureFake

HOME = (45.0, 5.0)


def _window(year: int, first: tuple[int, int], last: tuple[int, int]) -> DateRange:
    return DateRange(datetime(year, *first, tzinfo=UTC), datetime(year, *last, 23, 59, tzinfo=UTC))


def _read(days: list[datetime], ranges: tuple[DateRange, ...], *, undated=frozenset()):
    """One episode per day of `days`; an episode in `undated` carries no day, as one whose
    pictures the editor cannot select does."""
    assets, moments = {}, {}
    for index, day in enumerate(days):
        ids = []
        for n in range(3):
            asset_id = f"d{index:02}-{n}"
            assets[asset_id] = PictureFake(
                id=asset_id,
                file_created_at=day + timedelta(hours=12, minutes=n),
                is_favorite=False,
                is_video=False,
                exif_info=SimpleNamespace(city=None, place_name=None),
                people=[],
            )
            ids.append(asset_id)
        moments[f"M{index:02}"] = tuple(ids)
    source = SimpleNamespace(
        assets=assets,
        moment_asset_ids=moments,
        gps=dict.fromkeys(assets, HOME),
        annotations={},
        audience_annotations={},
        config=SimpleNamespace(
            trips=TripsConfig(homebase_latitude=HOME[0], homebase_longitude=HOME[1]),
            editorial=SimpleNamespace(people=EditorialPeopleConfig()),
            title_screens=SimpleNamespace(locale="en"),
        ),
        intent=SimpleNamespace(product="holiday"),
        case=SimpleNamespace(celebrated_birthday=None, ranges=ranges, product="holiday", people=()),
        people=None,
    )

    def enrich(episodes):
        hints = {}
        for episode in episodes:
            members = [a for m in episode.moments for a in moments[m]]
            day = assets[members[0]].file_created_at.date().isoformat()
            hints[episode.key] = {
                "day": "" if episode.moments[0] in undated else day,
                "moments": 1,
                "pictures": len(members),
                "favourites": 0,
                "gate": "maybe",
            }
        return hints

    story = RuleStructureReader(source).read_story(
        None, evidence=[], enrich=enrich, record=lambda _record: None
    )
    return [
        sorted(
            {
                assets[moments[m][0]].file_created_at.year
                for k in s["episodes"]
                for e in story.episodes
                if e.key == k
                for m in e.moments
            }
        )
        for s in story.stories
    ]


def test_a_day_with_no_selectable_picture_stays_in_its_own_year():
    years = (2004, 2013, 2022)
    days = [datetime(y, 8, 15, tzinfo=UTC) for y in years]
    ranges = tuple(_window(y, (8, 13), (8, 17)) for y in years)

    stories = _read(days, ranges, undated={"M02"})

    assert sorted(stories) == [[2004], [2013], [2022]]


def test_days_running_on_from_one_occurrence_into_the_next_are_two_stories():
    # A day window (1-3 July) and a window that starts on its last day, all four days inside
    # one calendar week.
    days = [datetime(2025, 7, d, tzinfo=UTC) for d in (1, 2, 3, 4)]
    ranges = (
        _window(2025, (7, 1), (7, 3)),
        DateRange(datetime(2025, 7, 3, tzinfo=UTC), datetime(2026, 7, 2, 23, 59, tzinfo=UTC)),
    )

    assert len(_read(days, ranges)) == 2


def test_new_years_eve_into_new_years_day_is_one_occurrence():
    days = [datetime(2024, 12, 31, tzinfo=UTC), datetime(2025, 1, 1, tzinfo=UTC)]
    ranges = (
        DateRange(datetime(2023, 12, 30, tzinfo=UTC), datetime(2024, 1, 2, 23, 59, tzinfo=UTC)),
        DateRange(datetime(2024, 12, 30, tzinfo=UTC), datetime(2025, 1, 2, 23, 59, tzinfo=UTC)),
    )

    assert len(_read(days, ranges)) == 1
