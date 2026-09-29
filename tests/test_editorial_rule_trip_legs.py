"""The rules reader keeps a trip whole, except where it changes where it stays (#1563)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace

from immich_memories.analysis.editorial_rule_reader import RuleStructureReader
from immich_memories.config_models_editorial import EditorialPeopleConfig

HOME = (48.0, 11.0)
KM = 1 / 111.0


def _read_trip(days: dict[int, tuple[float, float]]) -> list[list[int]]:
    """The stories the rules reader forms, as lists of days of the month."""
    assets, moments, gps, annotations = {}, {}, {}, {}
    for day, (lat, lon) in days.items():
        ids = []
        for n in range(8):
            asset_id = f"d{day:02}-{n:03}"
            taken = datetime(2022, 4, day, 9) + timedelta(minutes=n)
            assets[asset_id] = SimpleNamespace(
                id=asset_id,
                file_created_at=taken,
                is_favorite=day < 10,
                is_video=False,
                exif_info=None,
                people=[],
            )
            gps[asset_id] = (lat, lon)
            annotations[asset_id] = f"{taken.isoformat()} | walking | alone"
            ids.append(asset_id)
        moments[f"M{day:02}"] = tuple(ids)
    source = SimpleNamespace(
        assets=assets,
        moment_asset_ids=moments,
        gps=gps,
        annotations=annotations,
        audience_annotations={},
        config=SimpleNamespace(
            trips=SimpleNamespace(homebase_latitude=HOME[0], homebase_longitude=HOME[1]),
            editorial=SimpleNamespace(people=EditorialPeopleConfig()),
        ),
        intent=SimpleNamespace(product="trip"),
        case=SimpleNamespace(product="trip", people=()),
        people=None,
    )

    def enrich(episodes):
        return {
            e.key: {
                "day": date(2022, 4, int(e.moments[0][1:])).isoformat(),
                "moments": 1,
                "pictures": 8,
                "favourites": 8 if int(e.moments[0][1:]) < 10 else 0,
                "gate": "remarkable",
                "relations": {},
            }
            for e in episodes
        }

    story = RuleStructureReader(source).read_story(
        None, evidence=[], enrich=enrich, record=lambda _record: None
    )
    day_of = {e.key: int(e.moments[0][1:]) for e in story.episodes}
    return sorted(sorted(day_of[k] for k in row["episodes"]) for row in story.stories)


def test_a_hike_then_a_city_stay_are_two_stories():
    hike = {4 + i: (50.9 + i * 7 * KM, 14.0) for i in range(6)}
    city = {10 + i: (52.5, 13.4 + i * KM) for i in range(3)}

    assert _read_trip({**hike, **city}) == [[4, 5, 6, 7, 8, 9], [10, 11, 12]]


def test_a_road_trip_stays_one_story():
    road = {1 + i: (45.0 + i * 60 * KM, 12.0) for i in range(8)}

    assert _read_trip(road) == [list(range(1, 9))]
